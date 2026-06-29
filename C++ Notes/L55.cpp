// ============================================================
// L55: Order Matching Engine
// ============================================================
// WHAT: A matching engine pairs incoming orders against resting
//       orders in the order book using price-time priority (FIFO).
//       Supports limit orders, market orders, IOC, and FOK.
//       Generates Fill records for each execution.
// WHY (TRADING): You need a matching engine for:
//   1. Paper trading / simulation — testing strategies without real risk
//   2. Backtesting — replaying historical data with realistic fills
//   3. Building a trading venue (ECN, dark pool, crypto exchange)
//   Understanding how matching works reveals WHY your orders get
//   partial fills, why queue position matters, and how aggressive
//   orders sweep through the book level by level.
// PHASE: Trading Systems Implementation
// ============================================================

/*
  CONCEPT OVERVIEW:

  PRICE-TIME PRIORITY (FIFO MATCHING):
    1. Price priority: better price always fills first
       - Buys: higher bid fills before lower bid
       - Sells: lower ask fills before higher ask
    2. Time priority: at the same price, earlier arrival fills first
    This requires tracking individual orders at each price level,
    not just aggregate quantity (unlike L54's aggregated book).

  MATCHING ALGORITHM (for an incoming buy order at price P):
    1. Look at the ask side: take resting orders with ask_price <= P
    2. At each price level, fill in FIFO order (oldest order first)
    3. Continue sweeping until: order filled, no more matchable asks,
       or (for IOC/FOK) give up
    4. Remainder:
       - LIMIT: rest at P in the bid queue
       - MARKET: cancel remainder (no resting market orders)
       - IOC: cancel remainder
       - FOK: if not fully filled immediately → cancel entire order

  ORDER QUEUE AT EACH PRICE LEVEL:
    Instead of a single aggregated qty, we keep a queue of individual
    orders sorted by arrival time (FIFO). Use std::deque<QueuedOrder>.

  SELF-TRADE PREVENTION:
    If an incoming order would match against one of your own resting
    orders (same account), most exchanges reject it or cancel the
    resting order. We implement a simple check here.

  COMMON MISTAKES:
    - Not removing empty price levels from the book after full fill
    - Forgetting to handle partial fills on the passive (resting) side
    - Matching FOK orders partially and then not cancelling remainder
    - Not applying price improvement: if a resting order at ask=$182.74
      is matched by an incoming buy at $182.80, the fill happens at $182.74
      (the maker's price, not the taker's price)
*/

#include <iostream>
#include <map>
#include <deque>
#include <vector>
#include <functional>
#include <cstdint>
#include <cassert>
#include <optional>
#include <string>

// ============================================================
// PRICE / SIDE / TYPE (reuse definitions from L53)
// ============================================================

constexpr int64_t PRICE_MULT = 10000;
constexpr int64_t to_ticks(double p) { return static_cast<int64_t>(p * PRICE_MULT + 0.5); }
constexpr double  to_price(int64_t t){ return static_cast<double>(t)  / PRICE_MULT; }

enum class Side      : uint8_t { BUY = 0, SELL = 1 };
enum class OrderType : uint8_t { LIMIT = 0, MARKET = 1, IOC = 2, FOK = 3 };
enum class OrdStatus : uint8_t { NEW=0, PARTIAL=1, FILLED=2, CANCELLED=3, REJECTED=4 };

static uint64_t g_order_seq  = 1;
static uint64_t g_fill_seq   = 1;

// ============================================================
// QUEUED ORDER — resting in the book at a price level
// ============================================================

struct QueuedOrder {
    uint64_t  order_id;
    uint64_t  account_id;  // for self-trade prevention
    int32_t   qty;         // remaining quantity
    int32_t   orig_qty;    // original order quantity
    uint64_t  arrival_seq; // lower = earlier in queue (time priority)
};

// ============================================================
// FILL RECORD — generated for each execution
// ============================================================

struct Fill {
    uint64_t fill_id;
    uint64_t aggressor_order_id;  // incoming order that triggered the match
    uint64_t passive_order_id;    // resting order in the book
    int64_t  price;               // fill price = passive order's price (maker price)
    int32_t  qty;                 // fill quantity
    Side     aggressor_side;      // side of the incoming order
};

// ============================================================
// MATCHING ENGINE
// ============================================================

class MatchingEngine {
public:
    // One price level = a queue of orders in FIFO order
    struct PriceLevel {
        int64_t price;
        std::deque<QueuedOrder> orders;

        int32_t total_qty() const {
            int32_t total = 0;
            for (const auto& o : orders) total += o.qty;
            return total;
        }
    };

    // Bids: descending (highest bid is best)
    using BidBook = std::map<int64_t, PriceLevel, std::greater<int64_t>>;
    // Asks: ascending (lowest ask is best)
    using AskBook = std::map<int64_t, PriceLevel, std::less<int64_t>>;

    // Callback invoked for every fill generated
    using FillCallback = std::function<void(const Fill&)>;

    explicit MatchingEngine(FillCallback on_fill = nullptr)
        : on_fill_(on_fill ? on_fill : [](const Fill&){}) {}

    // ── SUBMIT AN ORDER ──────────────────────────────────

    OrdStatus submit(uint64_t order_id, Side side, OrderType type,
                     int64_t price, int32_t qty, uint64_t account_id) {
        if (qty <= 0) return OrdStatus::REJECTED;
        if (type == OrderType::LIMIT && price <= 0) return OrdStatus::REJECTED;

        // FOK: check if the order can be fully filled before touching the book
        if (type == OrderType::FOK) {
            int32_t available = (side == Side::BUY)
                ? ask_qty_at_or_below(price)
                : bid_qty_at_or_above(price);
            if (available < qty) return OrdStatus::CANCELLED;  // FOK: cancel entire order
        }

        int32_t remaining = qty;
        OrdStatus result  = OrdStatus::NEW;

        if (side == Side::BUY) {
            // Match against asks: sweep levels where ask_price <= limit_price
            // For MARKET orders: sweep all asks regardless of price
            for (auto it = asks_.begin(); it != asks_.end() && remaining > 0; ) {
                int64_t ask_price = it->first;
                if (type == OrderType::LIMIT && ask_price > price) break;  // no more matchable levels

                PriceLevel& lvl = it->second;
                remaining = match_level(lvl, order_id, account_id, ask_price,
                                        Side::BUY, remaining);

                if (lvl.orders.empty())
                    it = asks_.erase(it);  // remove the now-empty price level
                else
                    ++it;
            }
        } else {  // SELL
            for (auto it = bids_.begin(); it != bids_.end() && remaining > 0; ) {
                int64_t bid_price = it->first;
                if (type == OrderType::LIMIT && bid_price < price) break;

                PriceLevel& lvl = it->second;
                remaining = match_level(lvl, order_id, account_id, bid_price,
                                        Side::SELL, remaining);

                if (lvl.orders.empty())
                    it = bids_.erase(it);
                else
                    ++it;
            }
        }

        // Determine final status
        if (remaining == 0) {
            result = OrdStatus::FILLED;
        } else if (remaining < qty) {
            result = OrdStatus::PARTIAL;
        }

        // IOC and FOK: cancel any unfilled quantity
        if (type == OrderType::IOC || type == OrderType::FOK) {
            if (remaining > 0) result = OrdStatus::CANCELLED;
        } else if (type == OrderType::LIMIT && remaining > 0) {
            // Rest remainder in the book at the limit price
            rest_order(order_id, account_id, price, remaining, side, qty);
            result = (result == OrdStatus::PARTIAL) ? OrdStatus::PARTIAL : OrdStatus::NEW;
        }
        // MARKET orders: remainder is cancelled (exchange typically does this)

        return result;
    }

    // ── CANCEL A RESTING ORDER ───────────────────────────

    bool cancel(uint64_t order_id, Side side, int64_t price) {
        auto& book = (side == Side::BUY) ? bids_ : asks_;
        // This is a simplified O(N) scan — production uses an order ID → iterator map
        auto it = book.find(price);
        if (it == book.end()) return false;

        auto& orders = it->second.orders;
        for (auto oit = orders.begin(); oit != orders.end(); ++oit) {
            if (oit->order_id == order_id) {
                orders.erase(oit);
                if (orders.empty()) book.erase(it);
                return true;
            }
        }
        return false;
    }

    // ── BOOK QUERIES ─────────────────────────────────────

    std::optional<int64_t> best_bid() const {
        if (bids_.empty()) return std::nullopt;
        return bids_.begin()->first;
    }

    std::optional<int64_t> best_ask() const {
        if (asks_.empty()) return std::nullopt;
        return asks_.begin()->first;
    }

    void print_book(int depth = 3) const {
        std::cout << "\n  ─── Matching Engine Book ───\n";
        auto ait = asks_.begin();
        std::vector<std::pair<int64_t, int32_t>> ask_vec;
        for (int i = 0; i < depth && ait != asks_.end(); ++i, ++ait)
            ask_vec.push_back({ait->first, ait->second.total_qty()});
        for (int i = (int)ask_vec.size()-1; i >= 0; --i)
            std::cout << "  ASK  $" << to_price(ask_vec[i].first)
                      << "  x " << ask_vec[i].second << "\n";

        auto sp = best_bid();
        auto sa = best_ask();
        if (sp && sa) std::cout << "  ─── spread " << (*sa - *sp) << " ticks ───\n";

        int shown = 0;
        for (auto& [price, lvl] : bids_) {
            std::cout << "  BID  $" << to_price(price)
                      << "  x " << lvl.total_qty() << "\n";
            if (++shown >= depth) break;
        }
    }

private:
    BidBook      bids_;
    AskBook      asks_;
    FillCallback on_fill_;
    uint64_t     arrival_seq_ = 0;

    // Match an incoming order against one price level; returns remaining qty
    int32_t match_level(PriceLevel& lvl, uint64_t aggressor_id,
                         uint64_t aggressor_account, int64_t fill_price,
                         Side aggressor_side, int32_t remaining) {
        for (auto& passive : lvl.orders) {
            if (remaining == 0) break;

            // Self-trade prevention: skip if same account
            if (passive.account_id == aggressor_account) continue;

            int32_t fill_qty = std::min(remaining, passive.qty);

            Fill f{};
            f.fill_id            = g_fill_seq++;
            f.aggressor_order_id = aggressor_id;
            f.passive_order_id   = passive.order_id;
            f.price              = fill_price;  // maker's price (passive side)
            f.qty                = fill_qty;
            f.aggressor_side     = aggressor_side;

            on_fill_(f);  // notify caller

            passive.qty -= fill_qty;
            remaining   -= fill_qty;
        }

        // Remove fully filled passive orders from the queue
        while (!lvl.orders.empty() && lvl.orders.front().qty == 0)
            lvl.orders.pop_front();

        return remaining;
    }

    void rest_order(uint64_t order_id, uint64_t account_id,
                    int64_t price, int32_t qty, Side side, int32_t orig_qty) {
        QueuedOrder q{};
        q.order_id    = order_id;
        q.account_id  = account_id;
        q.qty         = qty;
        q.orig_qty    = orig_qty;
        q.arrival_seq = ++arrival_seq_;

        if (side == Side::BUY) {
            bids_[price].price = price;
            bids_[price].orders.push_back(q);
        } else {
            asks_[price].price = price;
            asks_[price].orders.push_back(q);
        }
    }

    int32_t ask_qty_at_or_below(int64_t max_price) const {
        int32_t total = 0;
        for (auto& [p, lvl] : asks_) {
            if (p > max_price) break;
            total += lvl.total_qty();
        }
        return total;
    }

    int32_t bid_qty_at_or_above(int64_t min_price) const {
        int32_t total = 0;
        for (auto& [p, lvl] : bids_) {
            if (p < min_price) break;
            total += lvl.total_qty();
        }
        return total;
    }
};

// ============================================================
// MAIN
// ============================================================

int main() {
    // Collect fills for display
    std::vector<Fill> all_fills;

    MatchingEngine engine([&](const Fill& f) {
        all_fills.push_back(f);
        std::cout << "  FILL #" << f.fill_id
                  << " | order " << f.aggressor_order_id
                  << " vs " << f.passive_order_id
                  << " | $" << to_price(f.price)
                  << " x " << f.qty
                  << " | side=" << (f.aggressor_side == Side::BUY ? "BUY" : "SELL")
                  << "\n";
    });

    std::cout << "=== Matching Engine Demo ===\n";

    // -------------------------------------------------------
    // POPULATE THE BOOK WITH RESTING LIMIT ORDERS
    // -------------------------------------------------------

    std::cout << "\n--- Resting limit orders (adds to book) ---\n";

    // Three sellers at different ask levels (account 1)
    engine.submit(g_order_seq++, Side::SELL, OrderType::LIMIT, to_ticks(182.75), 200, /*acct=*/1);
    engine.submit(g_order_seq++, Side::SELL, OrderType::LIMIT, to_ticks(182.75), 300, /*acct=*/2);
    engine.submit(g_order_seq++, Side::SELL, OrderType::LIMIT, to_ticks(182.76), 500, /*acct=*/3);
    engine.submit(g_order_seq++, Side::SELL, OrderType::LIMIT, to_ticks(182.77), 1000,/*acct=*/4);

    // Three buyers at different bid levels
    engine.submit(g_order_seq++, Side::BUY, OrderType::LIMIT, to_ticks(182.74), 400, /*acct=*/5);
    engine.submit(g_order_seq++, Side::BUY, OrderType::LIMIT, to_ticks(182.73), 600, /*acct=*/6);

    engine.print_book(5);

    // -------------------------------------------------------
    // AGGRESSIVE BUY: sweeps multiple levels
    // -------------------------------------------------------

    std::cout << "\n--- Aggressive BUY LIMIT @ $182.76 x 400 (sweeps asks) ---\n";
    all_fills.clear();

    OrdStatus st = engine.submit(g_order_seq++, Side::BUY, OrderType::LIMIT,
                                  to_ticks(182.76), 400, /*acct=*/10);

    std::cout << "  Status: ";
    switch (st) {
        case OrdStatus::FILLED:    std::cout << "FILLED\n"; break;
        case OrdStatus::PARTIAL:   std::cout << "PARTIAL\n"; break;
        case OrdStatus::CANCELLED: std::cout << "CANCELLED\n"; break;
        default:                   std::cout << "NEW (resting)\n"; break;
    }

    engine.print_book(5);

    // -------------------------------------------------------
    // IOC ORDER: fill what's available, cancel rest
    // -------------------------------------------------------

    std::cout << "\n--- IOC BUY @ $182.75 x 500 (partial fill, rest cancelled) ---\n";
    all_fills.clear();

    st = engine.submit(g_order_seq++, Side::BUY, OrderType::IOC,
                        to_ticks(182.75), 500, /*acct=*/11);

    std::cout << "  Status: " << (st == OrdStatus::FILLED ? "FILLED" :
                                    st == OrdStatus::PARTIAL ? "PARTIAL" :
                                    st == OrdStatus::CANCELLED ? "CANCELLED" : "NEW") << "\n";
    std::cout << "  (IOC: filled " << (all_fills.empty() ? 0 : all_fills[0].qty)
              << " shares, cancelled remainder)\n";

    engine.print_book(5);

    // -------------------------------------------------------
    // FOK ORDER: must fill entirely or not at all
    // -------------------------------------------------------

    std::cout << "\n--- FOK BUY @ $182.75 x 1000 (fails: not enough qty) ---\n";
    all_fills.clear();

    st = engine.submit(g_order_seq++, Side::BUY, OrderType::FOK,
                        to_ticks(182.75), 1000, /*acct=*/12);

    std::cout << "  Status: " << (st == OrdStatus::CANCELLED ? "CANCELLED (FOK rejected)" : "FILLED") << "\n";
    std::cout << "  Fills generated: " << all_fills.size() << " (should be 0 — FOK pre-check)\n";

    // -------------------------------------------------------
    // MARKET ORDER: sweeps at any price
    // -------------------------------------------------------

    std::cout << "\n--- MARKET SELL x 200 (sweeps best bid) ---\n";
    all_fills.clear();

    st = engine.submit(g_order_seq++, Side::SELL, OrderType::MARKET,
                        0, 200, /*acct=*/13);

    std::cout << "  Status: " << (st == OrdStatus::FILLED ? "FILLED" : "PARTIAL/CANCELLED") << "\n";

    engine.print_book(5);

    // -------------------------------------------------------
    // SELF-TRADE PREVENTION
    // -------------------------------------------------------

    std::cout << "\n--- Self-trade prevention: buy against own resting sell ---\n";
    all_fills.clear();

    // Add a resting sell from account 20
    engine.submit(g_order_seq++, Side::SELL, OrderType::LIMIT, to_ticks(182.80), 100, /*acct=*/20);
    // Now account 20 tries to buy at a price that would match its own sell
    st = engine.submit(g_order_seq++, Side::BUY, OrderType::IOC,
                        to_ticks(182.80), 100, /*acct=*/20);

    std::cout << "  Fills (should be 0 — self-trade skipped): " << all_fills.size() << "\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      In backtesting (L64), you replay historical ITCH messages:
        - AddOrder  → engine.submit(LIMIT) → goes into the book
        - DeleteOrder → engine.cancel() → removed from book
        - ExecuteOrder → note: exchange-reported fill, not our fill
      Your strategy's own orders are submitted against this simulated book.
      Realistic fill simulation requires modeling queue position:
        - If your order arrives AFTER others at the same price,
          you are behind them in queue — you may not get filled
          if only partial quantity trades at that level.
      This engine handles queue position via FIFO — orders submitted
      earlier fill first, matching real exchange behavior.
    */
}
