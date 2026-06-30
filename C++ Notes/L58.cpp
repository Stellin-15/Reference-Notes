// ============================================================
// L58: Market Data Feed Handler
// ============================================================
// WHAT: The feed handler is the first component in a live trading
//       system. It receives raw UDP/TCP packets from the exchange,
//       parses them (ITCH, FIX, MDP), tracks sequence numbers,
//       detects gaps, and publishes parsed market data events
//       to downstream components (order book, strategy) via a
//       lock-free SPSC queue.
// WHY (TRADING): The feed handler sets the latency floor for your
//   entire system. If the feed handler takes 5µs to parse a packet,
//   your strategy can never respond faster than 5µs — regardless
//   of how fast the rest of the system is. Every nanosecond saved
//   here is a nanosecond saved end-to-end.
//   Key decisions: zero-copy parsing, stack-allocated buffers,
//   no malloc in the hot path, sequence-number gap detection.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  FEED HANDLER ARCHITECTURE:
    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
    │  NIC / DPDK  │───►│ Feed Handler│───►│  SPSC Queue  │───► Strategy
    │  (L46/L52)   │    │  - Recv     │    │  (L38)       │    / BookUpdater
    └──────────────┘    │  - Seq chk  │    └──────────────┘
                        │  - Parse    │
                        │  - Publish  │
                        └─────────────┘

  SEQUENCE NUMBER TRACKING:
    Exchange feeds assign monotonic sequence numbers to each message.
    If we receive seq 5 after seq 3 → gap at 4 → request retransmit.
    Gap detection must be cheap: one integer compare per message.

  GAP RECOVERY STRATEGIES:
    1. Retransmission request: send a REQUEUEST to the exchange TCP channel
    2. Snapshot + replay: re-subscribe to get a full snapshot, then replay delta
    3. Multicast retransmit: some feeds (CME) offer a separate retransmit channel
    In practice: small gaps → retransmit; large gaps → reconnect.

  MARKET DATA EVENTS (what the feed handler publishes):
    BBO_UPDATE: new best bid or ask
    ADD_ORDER:  new resting limit order
    EXEC:       execution (fill) on a resting order
    CANCEL:     cancellation of resting order
    TRADE:      a non-display trade (dark pool)
    HALT:       trading halted for a symbol

  ZERO-COPY DESIGN:
    1. Receive bytes directly into a static buffer (no malloc)
    2. Parse in-place using reinterpret_cast (no copy to intermediate struct)
    3. Publish event to SPSC queue — only event metadata, not the raw bytes

  COMMON MISTAKES:
    - malloc() inside the receive loop (destroys latency predictability)
    - std::string for symbol names in events (heap allocation on every event)
    - Forgetting to handle out-of-order packets (UDP doesn't guarantee order)
    - Not resetting sequence state on reconnect
    - Processing messages from multiple symbols in a single thread
      without separate queues (one slow symbol blocks all others)
*/

#include <iostream>
#include <cstdint>
#include <cstring>
#include <atomic>
#include <array>
#include <cassert>
#include <functional>
#include <string>
#include <optional>
#include <chrono>
#include <thread>

// ============================================================
// MARKET DATA EVENT — what the feed handler publishes
// ============================================================

enum class MktEventType : uint8_t {
    ADD_ORDER  = 0,
    CANCEL     = 1,
    EXECUTE    = 2,
    TRADE      = 3,
    BBO_UPDATE = 4,
    HALT       = 5,
    RESUME     = 6,
    UNKNOWN    = 255
};

struct alignas(64) MktEvent {
    MktEventType type;
    char         symbol[8];    // null-padded
    uint64_t     order_ref;    // unique order reference (for ADD/CANCEL/EXEC)
    char         side;         // 'B' or 'S' (for ADD and EXECUTE)
    int64_t      price;        // in internal ticks (×10000 of a dollar)
    int32_t      qty;          // quantity (positive)
    uint64_t     timestamp_ns; // exchange timestamp (ns since midnight)
    uint64_t     seq_num;      // exchange sequence number
    char         _pad[3];      // pad to 64 bytes
};

static_assert(sizeof(MktEvent) == 64, "MktEvent should fit in one cache line");

// ============================================================
// SPSC QUEUE (simplified version from L38)
// ============================================================

template<typename T, int N>
class SPSCQueue {
    static_assert((N & (N-1)) == 0, "N must be power of 2");
    alignas(64) std::atomic<uint64_t> head_{0};
    alignas(64) std::atomic<uint64_t> tail_{0};
    T buf_[N]{};

public:
    bool push(const T& item) noexcept {
        uint64_t h = head_.load(std::memory_order_relaxed);
        if (h - tail_.load(std::memory_order_acquire) >= N) return false;
        buf_[h & (N-1)] = item;
        head_.store(h + 1, std::memory_order_release);
        return true;
    }

    bool pop(T& item) noexcept {
        uint64_t t = tail_.load(std::memory_order_relaxed);
        if (head_.load(std::memory_order_acquire) == t) return false;
        item = buf_[t & (N-1)];
        tail_.store(t + 1, std::memory_order_release);
        return true;
    }
};

// ============================================================
// SEQUENCE TRACKER — detects gaps in the message stream
// ============================================================

class SequenceTracker {
public:
    explicit SequenceTracker(const std::string& feed_name)
        : feed_name_(feed_name), expected_(1) {}

    // Check if this sequence number is expected, out-of-order, or a gap.
    // Returns: 0=ok, >0=gap size (missing messages), -1=duplicate/old
    int check(uint64_t seq) {
        if (seq == expected_) {
            ++expected_;
            return 0;   // exactly what we expected
        } else if (seq > expected_) {
            int gap = static_cast<int>(seq - expected_);
            ++gaps_detected_;
            last_gap_start_ = expected_;
            last_gap_size_  = gap;
            expected_ = seq + 1;  // advance past the gap
            return gap;
        } else {
            ++duplicates_;
            return -1;  // old or duplicate sequence number
        }
    }

    void reset(uint64_t next_expected = 1) {
        expected_    = next_expected;
        gaps_detected_ = 0;
        duplicates_   = 0;
    }

    uint64_t expected()      const { return expected_; }
    int      gaps_detected() const { return gaps_detected_; }
    int      duplicates()    const { return duplicates_; }
    uint64_t last_gap_start()const { return last_gap_start_; }
    int      last_gap_size() const { return last_gap_size_; }

private:
    std::string feed_name_;
    uint64_t    expected_      = 1;
    int         gaps_detected_ = 0;
    int         duplicates_    = 0;
    uint64_t    last_gap_start_= 0;
    int         last_gap_size_ = 0;
};

// ============================================================
// STATIC RECEIVE BUFFER — no malloc on the hot path
// ============================================================

constexpr int MAX_PKT_SIZE  = 65535;
constexpr int RECV_BUF_SIZE = 4096;  // number of events in SPSC queue

static uint8_t g_recv_buf[MAX_PKT_SIZE];  // single receive buffer (single-threaded recv)

// ============================================================
// FEED HANDLER
// ============================================================

class FeedHandler {
public:
    using EventQueue = SPSCQueue<MktEvent, RECV_BUF_SIZE>;

    explicit FeedHandler(const std::string& symbol,
                         const std::string& feed_name,
                         EventQueue& queue)
        : symbol_(symbol)
        , seq_tracker_(feed_name)
        , out_queue_(queue)
    {
        memset(symbol_buf_, 0, sizeof(symbol_buf_));
        // Copy symbol into fixed-width buffer
        for (size_t i = 0; i < symbol.size() && i < 8; ++i)
            symbol_buf_[i] = symbol[i];
    }

    // Process a raw ITCH 5.0 message (already extracted from UDP frame).
    // buf: pointer to message type byte (first byte is msg_type)
    // len: message length in bytes
    void process_itch_message(const uint8_t* buf, int len) {
        if (len < 1) return;
        ++messages_received_;

        uint8_t msg_type = buf[0];
        MktEvent evt{};
        evt.timestamp_ns = message_timestamp(buf, len);
        memcpy(evt.symbol, symbol_buf_, 8);

        switch (msg_type) {
            case 'A': parse_add_order(buf, len, evt);     break;
            case 'E': parse_executed(buf, len, evt);      break;
            case 'X': parse_cancel(buf, len, evt);        break;
            case 'D': parse_delete(buf, len, evt);        break;
            default:  evt.type = MktEventType::UNKNOWN;  break;
        }

        if (evt.type != MktEventType::UNKNOWN) {
            if (!out_queue_.push(evt)) ++dropped_events_;
        }
    }

    // Simulates receiving a stream of pre-framed messages (for testing).
    // In production, this is replaced by a real socket recv() or DPDK poll.
    void simulate_receive(const std::vector<std::pair<const uint8_t*, int>>& messages) {
        for (auto& [buf, len] : messages) {
            process_itch_message(buf, len);
        }
    }

    uint64_t messages_received()  const { return messages_received_; }
    uint64_t dropped_events()     const { return dropped_events_; }
    const SequenceTracker& seq()  const { return seq_tracker_; }

private:
    std::string    symbol_;
    char           symbol_buf_[8];
    SequenceTracker seq_tracker_;
    EventQueue&    out_queue_;
    uint64_t       messages_received_ = 0;
    uint64_t       dropped_events_    = 0;

    // Extract timestamp from ITCH message (bytes 3-10, big-endian uint64)
    uint64_t message_timestamp(const uint8_t* buf, int len) const {
        if (len < 11) return 0;
        uint64_t ts = 0;
        for (int i = 3; i < 11; ++i) ts = (ts << 8) | buf[i];
        return ts;
    }

    // Helper: read big-endian uint32 from buffer at offset
    static uint32_t read_be32(const uint8_t* buf, int offset) {
        return (static_cast<uint32_t>(buf[offset])   << 24) |
               (static_cast<uint32_t>(buf[offset+1]) << 16) |
               (static_cast<uint32_t>(buf[offset+2]) <<  8) |
               (static_cast<uint32_t>(buf[offset+3]));
    }

    // Helper: read big-endian uint64 from buffer at offset
    static uint64_t read_be64(const uint8_t* buf, int offset) {
        uint64_t v = 0;
        for (int i = 0; i < 8; ++i) v = (v << 8) | buf[offset + i];
        return v;
    }

    void parse_add_order(const uint8_t* buf, int len, MktEvent& evt) {
        if (len < 36) return;
        evt.type      = MktEventType::ADD_ORDER;
        evt.order_ref = read_be64(buf, 11);
        evt.side      = static_cast<char>(buf[19]);   // 'B' or 'S'
        evt.qty       = static_cast<int32_t>(read_be32(buf, 20));
        uint32_t itch_price = read_be32(buf, 32);
        evt.price     = static_cast<int64_t>(itch_price) / 100;  // to internal ticks
    }

    void parse_executed(const uint8_t* buf, int len, MktEvent& evt) {
        if (len < 31) return;
        evt.type      = MktEventType::EXECUTE;
        evt.order_ref = read_be64(buf, 11);
        evt.qty       = static_cast<int32_t>(read_be32(buf, 19));
    }

    void parse_cancel(const uint8_t* buf, int len, MktEvent& evt) {
        if (len < 23) return;
        evt.type      = MktEventType::CANCEL;
        evt.order_ref = read_be64(buf, 11);
        evt.qty       = static_cast<int32_t>(read_be32(buf, 19));  // cancelled shares
    }

    void parse_delete(const uint8_t* buf, int len, MktEvent& evt) {
        if (len < 19) return;
        evt.type      = MktEventType::CANCEL;   // treat delete as cancel all
        evt.order_ref = read_be64(buf, 11);
        evt.qty       = -1;  // -1 signals "delete entire order"
    }
};

// ============================================================
// SYNTHETIC MESSAGE BUILDER (for testing without a real feed)
// ============================================================

static std::vector<uint8_t> make_itch_add(uint64_t ref, char side,
                                           uint32_t shares, uint32_t price_itch) {
    std::vector<uint8_t> msg(36, 0);
    msg[0] = 'A';
    msg[1] = 0; msg[2] = 1;   // stock_locate = 1
    msg[3] = 0; msg[4] = 0;   // tracking_num = 0
    // timestamp: bytes 3-10 (leaving as 0 for test)
    // order_ref: bytes 11-18
    uint64_t r = ref;
    for (int i = 18; i >= 11; --i, r >>= 8) msg[i] = r & 0xFF;
    msg[19] = static_cast<uint8_t>(side);
    // shares: bytes 20-23
    msg[20] = (shares >> 24) & 0xFF; msg[21] = (shares >> 16) & 0xFF;
    msg[22] = (shares >>  8) & 0xFF; msg[23] =  shares        & 0xFF;
    // stock: bytes 24-31 (SPY     )
    const char* sym = "SPY     ";
    memcpy(&msg[24], sym, 8);
    // price: bytes 32-35
    msg[32] = (price_itch >> 24) & 0xFF; msg[33] = (price_itch >> 16) & 0xFF;
    msg[34] = (price_itch >>  8) & 0xFF; msg[35] =  price_itch        & 0xFF;
    return msg;
}

// ============================================================
// CONSUMER: reads events from the SPSC queue and processes them
// ============================================================

struct BookUpdater {
    int events_processed = 0;
    int adds   = 0;
    int execs  = 0;
    int cancels= 0;

    void consume(FeedHandler::EventQueue& q, int max_events) {
        MktEvent evt;
        for (int i = 0; i < max_events && q.pop(evt); ++i) {
            ++events_processed;
            switch (evt.type) {
                case MktEventType::ADD_ORDER: ++adds;    break;
                case MktEventType::EXECUTE:   ++execs;   break;
                case MktEventType::CANCEL:    ++cancels; break;
                default: break;
            }
        }
    }
};

// ============================================================
// MAIN
// ============================================================

int main() {
    std::cout << "=== Market Data Feed Handler ===\n";
    std::cout << "  MktEvent size: " << sizeof(MktEvent) << " bytes "
              << "(should be 64 — one cache line)\n";

    // -------------------------------------------------------
    // SETUP
    // -------------------------------------------------------

    FeedHandler::EventQueue queue;
    FeedHandler handler("SPY", "NASDAQ_ITCH", queue);
    BookUpdater updater;

    // -------------------------------------------------------
    // INJECT SYNTHETIC MESSAGES
    // -------------------------------------------------------

    std::cout << "\n=== Injecting synthetic ITCH messages ===\n";

    // Add 5 orders
    for (int i = 1; i <= 5; ++i) {
        uint32_t price_itch = 182500000 + i * 10000;  // $182.50 + i cents
        auto msg = make_itch_add(1000 + i, 'B', 100 * i, price_itch);
        handler.process_itch_message(msg.data(), static_cast<int>(msg.size()));
    }

    // Execute message (ref=1001, qty=50)
    {
        std::vector<uint8_t> exec_msg(31, 0);
        exec_msg[0] = 'E';
        uint64_t ref = 1001;
        for (int i = 18; i >= 11; --i, ref >>= 8) exec_msg[i] = ref & 0xFF;
        uint32_t qty = 50;
        exec_msg[19] = (qty >> 24) & 0xFF; exec_msg[20] = (qty >> 16) & 0xFF;
        exec_msg[21] = (qty >>  8) & 0xFF; exec_msg[22] =  qty        & 0xFF;
        handler.process_itch_message(exec_msg.data(), static_cast<int>(exec_msg.size()));
    }

    // Delete message (ref=1002)
    {
        std::vector<uint8_t> del_msg(19, 0);
        del_msg[0] = 'D';
        uint64_t ref = 1002;
        for (int i = 18; i >= 11; --i, ref >>= 8) del_msg[i] = ref & 0xFF;
        handler.process_itch_message(del_msg.data(), static_cast<int>(del_msg.size()));
    }

    std::cout << "  Messages sent to handler: " << handler.messages_received() << "\n";

    // -------------------------------------------------------
    // CONSUME EVENTS FROM THE QUEUE
    // -------------------------------------------------------

    updater.consume(queue, 1000);

    std::cout << "  Events consumed: " << updater.events_processed << "\n";
    std::cout << "    Adds:    " << updater.adds    << "\n";
    std::cout << "    Execs:   " << updater.execs   << "\n";
    std::cout << "    Cancels: " << updater.cancels << "\n";
    std::cout << "  Dropped (queue full): " << handler.dropped_events() << "\n";

    // -------------------------------------------------------
    // SEQUENCE GAP DETECTION DEMO
    // -------------------------------------------------------

    std::cout << "\n=== Sequence gap detection ===\n";

    SequenceTracker tracker("TEST_FEED");
    for (uint64_t seq : {1ULL, 2ULL, 3ULL, 5ULL, 6ULL, 7ULL, 10ULL}) {
        int result = tracker.check(seq);
        if (result == 0)
            std::cout << "  seq " << seq << ": OK\n";
        else if (result > 0)
            std::cout << "  seq " << seq << ": GAP! Missing " << result
                      << " message(s) starting at " << tracker.last_gap_start() << "\n";
        else
            std::cout << "  seq " << seq << ": DUPLICATE/OLD\n";
    }

    std::cout << "  Total gaps detected: " << tracker.gaps_detected() << "\n";

    // -------------------------------------------------------
    // THROUGHPUT BENCHMARK
    // -------------------------------------------------------

    std::cout << "\n=== Throughput benchmark ===\n";

    FeedHandler::EventQueue bench_q;
    FeedHandler bench_handler("BENCH", "BENCH_FEED", bench_q);

    auto msg = make_itch_add(9999, 'B', 100, 182500000);
    constexpr int REPS = 1000000;

    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < REPS; ++i) {
        // Drain the queue to prevent it from filling up
        if (i % 64 == 0) {
            MktEvent dummy;
            while (bench_q.pop(dummy)) {}
        }
        bench_handler.process_itch_message(msg.data(), static_cast<int>(msg.size()));
    }
    auto t1 = std::chrono::steady_clock::now();

    uint64_t total_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());

    std::cout << "  " << REPS << " messages processed in " << total_ns / 1000 << "µs\n";
    std::cout << "  Per message: " << total_ns / REPS << "ns\n";
    std::cout << "  Throughput: " << (REPS * 1000ULL) / (total_ns / 1000 + 1) << " K msg/sec\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Production feed handler for NASDAQ ITCH over multicast UDP:

        void feed_handler_main(int core_id) {
            pin_thread_to_core(core_id);             // L40: CPU affinity
            socket_t sock = create_multicast_receiver(  // L47: multicast
                "233.54.12.111", 26477, "10.0.0.1");

            uint8_t buf[65535];
            FeedHandler::EventQueue queue;
            FeedHandler handler("*", "ITCH", queue);  // all symbols

            while (running) {
                int len = recv(sock, buf, sizeof(buf), 0);  // or DPDK poll (L52)
                if (len <= 0) continue;
                // ITCH framing: each UDP payload contains 1+ messages
                // prefixed by uint16_t length (big-endian)
                int offset = 0;
                while (offset + 2 <= len) {
                    uint16_t msg_len = (buf[offset] << 8) | buf[offset+1];
                    offset += 2;
                    handler.process_itch_message(buf + offset, msg_len);
                    offset += msg_len;
                }
            }
        }
    */
}
