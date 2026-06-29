// ============================================================
// L47: Multicast UDP and Market Data
// ============================================================
// WHAT: IP multicast lets one sender deliver packets to many
//       receivers simultaneously without unicasting N copies.
//       Market data exchanges (CME, NASDAQ, NYSE) use multicast
//       UDP to broadcast prices to all connected subscribers.
// WHY (TRADING): This is HOW prices arrive. If you don't know
//   multicast, you don't know how your tick data gets to you.
//   NASDAQ ITCH, CME MDP 3.0, NYSE Pillar, OPRA — all are
//   multicast UDP feeds. Understanding sequence numbers, gap
//   detection, and retransmission is essential for building a
//   feed handler that never misses a price update.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  MULTICAST vs UNICAST vs BROADCAST:
    Unicast:   one sender → one receiver (TCP, point-to-point)
    Broadcast: one sender → ALL hosts on the subnet (wasteful)
    Multicast: one sender → subscribed receivers only
    Multicast IP range: 224.0.0.0 – 239.255.255.255

  HOW MULTICAST WORKS:
    1. Sender sends UDP packet to a multicast group IP (e.g., 233.54.12.111)
    2. Network switch/router replicates the packet to all subscribed ports
    3. Receiver subscribes with IP_ADD_MEMBERSHIP — kernel joins the group
    4. All subscribers receive the same packet simultaneously
    Result: exchange sends ONE packet, 100 trading firms all receive it.
    This is why colocation matters — your NIC is on the same VLAN as the source.

  SUBSCRIBING TO A MULTICAST GROUP (Linux/Windows):
    struct ip_mreq mreq;
    inet_pton(AF_INET, "233.54.12.111", &mreq.imr_multiaddr);  // group IP
    mreq.imr_interface.s_addr = INADDR_ANY;   // use default interface
    setsockopt(sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, &mreq, sizeof(mreq));
    Then: bind to port and call recvfrom() in a loop.

  SEQUENCE NUMBERS:
    Every multicast packet has a sequence number in its header.
    Feed handlers track the expected next sequence number.
    If expected=1000 and we receive 1002: gap detected (1001 missing).
    Possible causes: packet loss (UDP doesn't retransmit), out-of-order delivery.
    Response to gap: request retransmission via TCP recovery channel (if available).

  GAP DETECTION:
    uint32_t expected_seq = 0;
    void on_packet(const Header* h) {
        if (h->seq != expected_seq) {
            if (h->seq > expected_seq) {
                // Gap: we missed expected_seq to h->seq - 1
                request_retransmit(expected_seq, h->seq - 1);
            }
            // h->seq < expected_seq: duplicate or out-of-order (ignore)
        }
        process(h);
        expected_seq = h->seq + 1;
    }

  SNAPSHOT + DELTA:
    Many feeds send:
    1. Snapshot channel (TCP or slow UDP): complete state of the order book
    2. Delta channel (fast multicast UDP): incremental updates
    On start or after a gap: subscribe to snapshot, rebuild book from snapshot,
    then apply buffered deltas from where the snapshot ended.

  MULTICAST SOURCE ADDRESSES:
    CME Group (Globex): 224.0.28.x, 233.x.x.x
    NASDAQ ITCH: 233.54.12.x, 233.209.x.x
    OPRA (options): 233.43.x.x
    These are exchange-specific — check the market data specs.

  TRADING USE CASE:
    // Subscribe to NASDAQ ITCH multicast feed:
    // Group: 233.54.12.111, port: 26477
    // On each packet: parse ITCH message, update book

  COMMON MISTAKES:
    - Binding to the multicast group IP instead of INADDR_ANY (or the local IP)
      → correct: bind to port with INADDR_ANY, then join the multicast group
    - Forgetting to join the group (IP_ADD_MEMBERSHIP) → no packets received
    - Not handling out-of-order delivery (seq < expected) → double-processing
    - Buffer too small → recvfrom returns truncated packet → corrupt data
    - Confusing multicast port with TTL: set IP_MULTICAST_TTL > 1 for multi-hop
    - On Linux: set SO_REUSEADDR before bind to allow multiple processes to
      subscribe to the same multicast port on the same machine
*/

#include <iostream>
#include <cstring>
#include <cstdint>
#include <string>
#include <vector>
#include <thread>
#include <atomic>
#include <chrono>
#include <stdexcept>

// Platform socket headers
#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  pragma comment(lib, "Ws2_32.lib")
   using socket_t = SOCKET;
   static const socket_t INVALID_SOCK = INVALID_SOCKET;
#  define CLOSE_SOCK(s) closesocket(s)
#  define SOCK_ERR WSAGetLastError()
struct WinsockInit {
    WinsockInit() { WSADATA w{}; WSAStartup(MAKEWORD(2,2),&w); }
    ~WinsockInit() { WSACleanup(); }
};
#else
#  include <sys/socket.h>
#  include <netinet/in.h>
#  include <arpa/inet.h>
#  include <unistd.h>
#  include <fcntl.h>
#  include <errno.h>
   using socket_t = int;
   static const socket_t INVALID_SOCK = -1;
#  define CLOSE_SOCK(s) ::close(s)
#  define SOCK_ERR errno
#endif

using namespace std::chrono_literals;

// ============================================================
// SIMULATED ITCH-STYLE PACKET HEADER
// ============================================================

// NASDAQ ITCH packets have a sequence number in a session header.
// Every channel has its own sequence space starting from 1.
#pragma pack(push, 1)
struct PacketHeader {
    uint16_t msg_count;   // number of messages in this packet
    uint64_t seq_num;     // sequence number of first message
};

struct ITCHAddOrder {
    char     msg_type;    // 'A'
    uint32_t timestamp;   // nanoseconds past midnight (32-bit)
    uint64_t order_ref;
    char     side;        // 'B' or 'S'
    uint32_t shares;
    char     stock[8];
    uint32_t price;       // price in 10000ths of a dollar
};

struct ITCHDeleteOrder {
    char     msg_type;    // 'D'
    uint32_t timestamp;
    uint64_t order_ref;
};

struct ITCHTrade {
    char     msg_type;    // 'P'
    uint32_t timestamp;
    uint64_t order_ref;
    char     side;
    uint32_t shares;
    char     stock[8];
    uint32_t price;
    uint64_t match_number;
};
#pragma pack(pop)

// ============================================================
// GAP DETECTOR
// ============================================================

class GapDetector {
public:
    explicit GapDetector(uint64_t first_expected = 1)
        : expected_(first_expected), gaps_detected_(0)
    {}

    // Returns true if this sequence is valid (in order, no gap).
    // Updates expected_ on success.
    bool check(uint64_t seq) {
        if (seq == expected_) {
            ++expected_;
            return true;
        }
        if (seq > expected_) {
            // Gap: missing seq expected_ through seq-1
            uint64_t gap_start = expected_;
            uint64_t gap_end   = seq - 1;
            ++gaps_detected_;
            std::cout << "  [GAP] Detected gap: missing seq "
                      << gap_start << " to " << gap_end
                      << " (" << (gap_end - gap_start + 1) << " messages)\n";
            std::cout << "  [GAP] Requesting retransmit from recovery channel...\n";
            expected_ = seq + 1;
            return true;  // process this packet, but note the gap
        }
        // seq < expected_: duplicate or out-of-order — ignore
        std::cout << "  [DUP] Ignoring duplicate seq=" << seq
                  << " (expected=" << expected_ << ")\n";
        return false;
    }

    uint64_t next_expected() const { return expected_; }
    int      gaps_detected() const { return gaps_detected_; }

private:
    uint64_t expected_;
    int      gaps_detected_;
};

// ============================================================
// MOCK FEED HANDLER — processes parsed ITCH messages
// ============================================================

struct OrderBookStats {
    int adds = 0, deletes = 0, trades = 0;
    int64_t total_traded_value = 0;
};

void process_message(const uint8_t* data, int len, OrderBookStats& stats) {
    if (len < 1) return;
    char msg_type = static_cast<char>(data[0]);

    switch (msg_type) {
        case 'A': {
            if (len < (int)sizeof(ITCHAddOrder)) return;
            auto* m = reinterpret_cast<const ITCHAddOrder*>(data);
            ++stats.adds;
            // In real code: insert into order book
            (void)m;
            break;
        }
        case 'D': {
            if (len < (int)sizeof(ITCHDeleteOrder)) return;
            ++stats.deletes;
            break;
        }
        case 'P': {
            if (len < (int)sizeof(ITCHTrade)) return;
            auto* m = reinterpret_cast<const ITCHTrade*>(data);
            ++stats.trades;
            stats.total_traded_value += int64_t(m->shares) * int64_t(m->price);
            break;
        }
        default:
            break;  // other message types — ignore for demo
    }
}

// ============================================================
// MULTICAST SOCKET HELPERS
// ============================================================

socket_t create_multicast_receiver(const char* group_ip,
                                   uint16_t port,
                                   const char* iface_ip = "0.0.0.0")
{
    socket_t sock = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == INVALID_SOCK) return INVALID_SOCK;

    // Allow multiple processes to bind to the same port on the same host
    int one = 1;
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, (const char*)&one, sizeof(one));

    // Increase receive buffer for burst market data
    int rcvbuf = 8 * 1024 * 1024;
    setsockopt(sock, SOL_SOCKET, SO_RCVBUF, (const char*)&rcvbuf, sizeof(rcvbuf));

    // Bind to the port on all interfaces (INADDR_ANY)
    sockaddr_in local_addr{};
    local_addr.sin_family = AF_INET;
    local_addr.sin_port   = htons(port);
    local_addr.sin_addr.s_addr = INADDR_ANY;

    if (::bind(sock, (sockaddr*)&local_addr, sizeof(local_addr)) < 0) {
        std::cerr << "  bind() failed: " << SOCK_ERR << "\n";
        CLOSE_SOCK(sock);
        return INVALID_SOCK;
    }

    // Join the multicast group
    struct ip_mreq mreq{};
    inet_pton(AF_INET, group_ip, &mreq.imr_multiaddr);
    inet_pton(AF_INET, iface_ip, &mreq.imr_interface);

    if (setsockopt(sock, IPPROTO_IP, IP_ADD_MEMBERSHIP,
                   (const char*)&mreq, sizeof(mreq)) < 0) {
        // This will fail on loopback/sandbox — show how it would be done
        std::cerr << "  IP_ADD_MEMBERSHIP failed (expected in sandbox): " << SOCK_ERR << "\n";
    }

    return sock;
}

// ============================================================
// LOOPBACK UDP SIMULATION
// ============================================================

// Simulate multicast by using loopback UDP (since we can't actually
// join a multicast group in a sandbox)
void simulate_feed_handler() {
    const uint16_t UDP_PORT = 22345;
    std::atomic<bool> server_ready{false};
    std::atomic<int>  packets_received{0};
    GapDetector       gap_detector(1);
    OrderBookStats    stats;

    // "Sender" thread: pushes UDP packets simulating an exchange feed
    std::thread sender([UDP_PORT, &server_ready]() {
        while (!server_ready.load(std::memory_order_acquire)) {
            std::this_thread::sleep_for(1ms);
        }

        socket_t sock = ::socket(AF_INET, SOCK_DGRAM, 0);
        if (sock == INVALID_SOCK) return;

        sockaddr_in dst{};
        dst.sin_family = AF_INET;
        dst.sin_port   = htons(UDP_PORT);
        inet_pton(AF_INET, "127.0.0.1", &dst.sin_addr);

        // Send 10 simulated ITCH packets (simulate a market data burst)
        uint64_t seq = 1;
        for (int i = 0; i < 10; ++i) {
            if (i == 5) { ++seq; }  // deliberately skip seq=6 to simulate a gap

            // Build a fake ITCH packet: header + one AddOrder message
            uint8_t pkt[sizeof(PacketHeader) + sizeof(ITCHAddOrder)];
            auto* hdr = reinterpret_cast<PacketHeader*>(pkt);
            hdr->msg_count = 1;
            hdr->seq_num   = seq++;

            auto* msg = reinterpret_cast<ITCHAddOrder*>(pkt + sizeof(PacketHeader));
            msg->msg_type  = 'A';
            msg->timestamp = uint32_t(i * 1000000);
            msg->order_ref = uint64_t(1000 + i);
            msg->side      = (i % 2 == 0) ? 'B' : 'S';
            msg->shares    = uint32_t(100 + i * 10);
            std::memcpy(msg->stock, "AAPL    ", 8);
            msg->price     = uint32_t(1825000 + i * 100);

            ::sendto(sock, (const char*)pkt, sizeof(pkt), 0, (sockaddr*)&dst, sizeof(dst));
            std::this_thread::sleep_for(1ms);
        }
        CLOSE_SOCK(sock);
    });

    // "Receiver" thread: simulates feed handler receiving and parsing
    std::thread receiver([UDP_PORT, &server_ready, &packets_received,
                          &gap_detector, &stats]() {
        socket_t sock = ::socket(AF_INET, SOCK_DGRAM, 0);
        if (sock == INVALID_SOCK) { server_ready.store(true); return; }

        int one = 1;
        setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, (const char*)&one, sizeof(one));
        int rcvbuf = 4 * 1024 * 1024;
        setsockopt(sock, SOL_SOCKET, SO_RCVBUF, (const char*)&rcvbuf, sizeof(rcvbuf));

        sockaddr_in local{};
        local.sin_family      = AF_INET;
        local.sin_port        = htons(UDP_PORT);
        local.sin_addr.s_addr = INADDR_ANY;
        ::bind(sock, (sockaddr*)&local, sizeof(local));

        server_ready.store(true, std::memory_order_release);

        uint8_t buf[65536];
        int total_expected = 10;

        while (packets_received.load(std::memory_order_relaxed) < total_expected) {
            sockaddr_in src{};
            socklen_t src_len = sizeof(src);
            int bytes = ::recvfrom(sock, (char*)buf, sizeof(buf), 0,
                                   (sockaddr*)&src, &src_len);
            if (bytes < (int)sizeof(PacketHeader)) continue;

            auto* hdr = reinterpret_cast<PacketHeader*>(buf);
            gap_detector.check(hdr->seq_num);

            // Process messages in the packet
            uint8_t* msg_ptr = buf + sizeof(PacketHeader);
            int msg_bytes    = bytes - (int)sizeof(PacketHeader);
            process_message(msg_ptr, msg_bytes, stats);

            packets_received.fetch_add(1, std::memory_order_relaxed);
        }
        CLOSE_SOCK(sock);
    });

    sender.join();
    receiver.join();

    std::cout << "  Packets received: " << packets_received.load() << "\n";
    std::cout << "  Gaps detected:    " << gap_detector.gaps_detected() << "\n";
    std::cout << "  Add orders:       " << stats.adds << "\n";
    std::cout << "  Next expected seq: " << gap_detector.next_expected() << "\n";
}

// ============================================================
// MAIN
// ============================================================

int main() {

#ifdef _WIN32
    WinsockInit wsa_init;
#endif

    // -------------------------------------------------------
    // GAP DETECTION DEMO
    // -------------------------------------------------------

    std::cout << "=== Gap detection ===\n";

    {
        GapDetector gd(1);
        // Simulate receiving packets with one gap
        uint64_t seqs[] = {1, 2, 3, 4, 7, 8, 9, 3};  // gap at 5-6, dup at 3
        for (uint64_t seq : seqs) {
            bool ok = gd.check(seq);
            std::cout << "  seq=" << seq << " ok=" << ok
                      << " next_expected=" << gd.next_expected() << "\n";
        }
        std::cout << "  Total gaps detected: " << gd.gaps_detected() << "\n";
    }

    // -------------------------------------------------------
    // MULTICAST SOCKET SETUP (just show config — won't join in sandbox)
    // -------------------------------------------------------

    std::cout << "\n=== Multicast socket setup ===\n";

    {
        socket_t sock = ::socket(AF_INET, SOCK_DGRAM, 0);
        if (sock != INVALID_SOCK) {
            // Show what a real multicast subscription looks like
            std::cout << "  Socket created for multicast demo\n";
            std::cout << "  To join NASDAQ ITCH group 233.54.12.111:26477:\n";
            std::cout << "    struct ip_mreq mreq;\n";
            std::cout << "    inet_pton(AF_INET, \"233.54.12.111\", &mreq.imr_multiaddr);\n";
            std::cout << "    mreq.imr_interface.s_addr = INADDR_ANY;\n";
            std::cout << "    setsockopt(sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, &mreq, sizeof(mreq));\n";
            CLOSE_SOCK(sock);
        }
    }

    // -------------------------------------------------------
    // LOOPBACK FEED SIMULATION
    // -------------------------------------------------------

    std::cout << "\n=== Loopback UDP feed handler simulation ===\n";
    simulate_feed_handler();

    // -------------------------------------------------------
    // MAJOR EXCHANGE FEED SUMMARY
    // -------------------------------------------------------

    std::cout << "\n=== Major exchange multicast feeds ===\n";

    std::cout << "  NASDAQ ITCH 5.0:\n"
              << "    Protocol:  Binary, multicast UDP\n"
              << "    Group:     233.54.12.x, various ports\n"
              << "    Seq num:   64-bit, per-session, starts at 1\n"
              << "    Recovery:  TCP MOLD64U retransmission server\n"
              << "    Messages:  AddOrder(A), CancelOrder(X), DeleteOrder(D), Trade(P)\n"
              << "\n"
              << "  CME Globex MDP 3.0:\n"
              << "    Protocol:  Binary, multicast UDP (SBE encoding)\n"
              << "    Group:     224.0.28.x, 233.x.x.x\n"
              << "    Channels:  Incremental (fast) + Snapshot (recovery)\n"
              << "\n"
              << "  NYSE Pillar:\n"
              << "    Protocol:  Binary, multicast UDP\n"
              << "    Messages:  AddOrder, ModifyOrder, DeleteOrder, Trade\n"
              << "\n"
              << "  OPRA (Options):\n"
              << "    Protocol:  Binary, multicast UDP\n"
              << "    Volume:    ~50-100 billion messages/day (highest volume)\n"
              << "    Requires:  SIMD or DPDK to keep up at peak rates\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Full multicast feed handler main loop (production pattern):

        void FeedHandler::run() {
            // Join multicast group
            socket_t sock = create_udp_socket();
            join_multicast_group(sock, group_ip_, port_);
            set_nonblocking(sock);

            uint8_t recv_buf[65536];
            GapDetector gap(1);

            while (running_.load(std::memory_order_relaxed)) {

                // Non-blocking receive (spin loop)
                int bytes = ::recv(sock, recv_buf, sizeof(recv_buf), MSG_DONTWAIT);

                if (bytes > 0) {
                    // Parse header, check sequence number
                    auto* hdr = reinterpret_cast<PacketHeader*>(recv_buf);

                    if (!gap.check(hdr->seq_num)) {
                        _mm_pause(); continue;   // duplicate — skip
                    }

                    // Parse all messages in the packet
                    const uint8_t* p = recv_buf + sizeof(PacketHeader);
                    const uint8_t* end = recv_buf + bytes;
                    while (p < end) {
                        int msg_len = parse_and_apply(*p, p, book_);
                        p += msg_len;
                    }

                    // Push updated BBO to strategy thread
                    bbo_queue_.push(book_.bbo());

                } else if (gap.detected_recently()) {
                    // Send retransmission request to TCP recovery channel
                    request_retransmit(gap.first_missing(), gap.last_missing());
                } else {
                    _mm_pause();   // no packet — spin with pause
                }
            }
        }
    */
}
