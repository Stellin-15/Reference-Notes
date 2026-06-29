// ============================================================
// L48: Non-Blocking I/O and epoll/select
// ============================================================
// WHAT: Non-blocking I/O lets a single thread monitor many
//       sockets simultaneously without blocking on any of them.
//       select() is portable but slow (O(n) scan).
//       poll() is slightly better. epoll (Linux) is O(1) and
//       scales to thousands of connections.
// WHY (TRADING): A gateway thread manages connections to:
//   - 2-5 exchanges (FIX order entry, one TCP per exchange)
//   - 5-20 market data feeds (UDP, one per asset class)
//   - Risk server connection (internal TCP)
//   - Admin connection (operator console)
//   With blocking I/O: one thread per socket (30+ threads, high
//   context switch overhead). With epoll: one gateway thread
//   monitors ALL sockets, wakes up ONLY when data arrives, no
//   spinning, no blocking. For market data hot paths, use
//   dedicated spin-loop threads (L41). For order management
//   (lower frequency, many connections), use epoll.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  SELECT:
    fd_set read_fds; FD_ZERO(&read_fds); FD_SET(sock, &read_fds);
    int n = select(max_fd + 1, &read_fds, NULL, NULL, &timeout);
    if (n > 0 && FD_ISSET(sock, &read_fds)) { // sock has data }
    Portable (Windows + Linux), but slow: O(n) — scans all fds.
    Max FD count: 1024 on most systems (FD_SETSIZE limit).

  POLL:
    struct pollfd fds[N]; fds[0].fd = sock; fds[0].events = POLLIN;
    int n = poll(fds, N, timeout_ms);
    if (fds[0].revents & POLLIN) { // sock has data }
    Better than select: no FD_SETSIZE limit, cleaner API.
    Still O(n) per call.

  EPOLL (Linux only, most efficient):
    int epfd = epoll_create1(0);                  — create epoll instance
    epoll_event ev; ev.events = EPOLLIN; ev.data.fd = sock;
    epoll_ctl(epfd, EPOLL_CTL_ADD, sock, &ev);    — register socket
    epoll_event events[64];
    int n = epoll_wait(epfd, events, 64, timeout_ms);  — wait for events
    for (int i=0; i<n; i++) { process(events[i].data.fd); }
    O(1): only returns ready fds. Scales to 100K+ connections.
    EPOLLET (edge-triggered): only notified on state change (faster, harder to use).
    EPOLLONESHOT: notified once, then disabled (re-arm manually).

  KQUEUE (macOS / BSD equivalent of epoll):
    Similar concept to epoll: kevent(), EV_ADD, EV_DELETE.
    Not covered here but same principles apply.

  WINDOWS IOCP (I/O Completion Ports):
    Windows equivalent: asynchronous overlapped I/O.
    Much more complex API. Used in production Windows trading systems.

  NON-BLOCKING PATTERN:
    Make socket non-blocking (fcntl O_NONBLOCK or ioctlsocket).
    Call recv() — if no data: returns -1, errno = EAGAIN.
    Use select/epoll to wait until data arrives, THEN recv().
    This way: thread never blocks, can handle multiple sockets.

  TIMEOUT:
    select/poll/epoll_wait take a timeout parameter.
    timeout = 0: return immediately (non-blocking poll).
    timeout = -1: wait forever.
    timeout = N ms: wait up to N ms, then return.
    In trading: small timeout (1-10ms) on order management thread.
    Market data thread: non-blocking recv with spin loop (L41).

  TRADING USE CASE:
    Gateway thread with epoll:
    - Monitors 5 FIX connections (one per exchange) for execution reports
    - When data arrives on exchange A: parse ExecutionReport, update position
    - When data arrives on exchange B: same
    - Timeout every 1ms: send heartbeats to all connections
    - All in ONE thread, no context switches between handlers

  COMMON MISTAKES:
    - Forgetting to make sockets non-blocking before using with epoll
    - Edge-triggered epoll: not draining all available data in one pass
      → missed events (must loop recv until EAGAIN)
    - select: modifying the fd_set after a failed call (select modifies it)
    - Not handling partial reads: recv() can return fewer bytes than requested
    - Timeout = 0 on epoll_wait in a tight loop: wastes CPU (use spin for HFT)
*/

#include <iostream>
#include <cstring>
#include <cstdint>
#include <string>
#include <vector>
#include <thread>
#include <atomic>
#include <chrono>
#include <functional>
#include <unordered_map>
#include <stdexcept>

// Platform headers
#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  pragma comment(lib, "Ws2_32.lib")
   using socket_t = SOCKET;
   static const socket_t INVALID_SOCK = INVALID_SOCKET;
#  define CLOSE_SOCK(s) closesocket(s)
#  define SOCK_ERR WSAGetLastError()
#  define EAGAIN_ERRNO WSAEWOULDBLOCK
struct WinsockInit {
    WinsockInit() { WSADATA w{}; WSAStartup(MAKEWORD(2,2),&w); }
    ~WinsockInit() { WSACleanup(); }
};
#else
#  include <sys/socket.h>
#  include <sys/select.h>
#  include <netinet/in.h>
#  include <arpa/inet.h>
#  include <unistd.h>
#  include <fcntl.h>
#  include <errno.h>
#  ifdef __linux__
#    include <sys/epoll.h>
#    define HAS_EPOLL 1
#  else
#    define HAS_EPOLL 0
#  endif
   using socket_t = int;
   static const socket_t INVALID_SOCK = -1;
#  define CLOSE_SOCK(s) ::close(s)
#  define SOCK_ERR errno
#  define EAGAIN_ERRNO EAGAIN
#endif

using namespace std::chrono_literals;

// ============================================================
// SOCKET HELPERS
// ============================================================

bool set_nonblocking(socket_t sock) {
#ifdef _WIN32
    u_long mode = 1;
    return ioctlsocket(sock, FIONBIO, &mode) == 0;
#else
    int flags = fcntl(sock, F_GETFL, 0);
    return flags >= 0 && fcntl(sock, F_SETFL, flags | O_NONBLOCK) == 0;
#endif
}

socket_t make_listener(uint16_t port) {
    socket_t s = ::socket(AF_INET, SOCK_STREAM, 0);
    if (s == INVALID_SOCK) return INVALID_SOCK;
    int one = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, (const char*)&one, sizeof(one));
    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(port);
    addr.sin_addr.s_addr = INADDR_ANY;
    ::bind(s, (sockaddr*)&addr, sizeof(addr));
    ::listen(s, 16);
    set_nonblocking(s);
    return s;
}

socket_t make_client(const char* host, uint16_t port) {
    socket_t s = ::socket(AF_INET, SOCK_STREAM, 0);
    if (s == INVALID_SOCK) return INVALID_SOCK;
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(port);
    inet_pton(AF_INET, host, &addr.sin_addr);
    if (::connect(s, (sockaddr*)&addr, sizeof(addr)) < 0) {
        CLOSE_SOCK(s);
        return INVALID_SOCK;
    }
    set_nonblocking(s);
    return s;
}

// ============================================================
// SELECT-BASED MULTI-SOCKET MONITOR
// ============================================================

// Monitors multiple sockets with select() — portable, easy to understand
class SelectMonitor {
public:
    using Handler = std::function<void(socket_t)>;

    void add(socket_t sock, Handler handler) {
        entries_.push_back({sock, handler});
    }

    // Run one iteration: wait up to timeout_ms for any socket to become readable
    int poll_once(int timeout_ms = 10) {
        fd_set rfds;
        FD_ZERO(&rfds);

        socket_t max_fd = 0;
        for (const auto& e : entries_) {
            FD_SET(e.sock, &rfds);
            if (e.sock > max_fd) max_fd = e.sock;
        }

        timeval tv{};
        tv.tv_sec  = timeout_ms / 1000;
        tv.tv_usec = (timeout_ms % 1000) * 1000;

        int n = ::select(static_cast<int>(max_fd) + 1, &rfds, nullptr, nullptr, &tv);
        if (n <= 0) return n;

        for (const auto& e : entries_) {
            if (FD_ISSET(e.sock, &rfds)) {
                e.handler(e.sock);
            }
        }
        return n;
    }

private:
    struct Entry { socket_t sock; Handler handler; };
    std::vector<Entry> entries_;
};

// ============================================================
// EPOLL-BASED EVENT LOOP (Linux only)
// ============================================================

#if HAS_EPOLL

class EpollEventLoop {
public:
    EpollEventLoop() {
        epfd_ = epoll_create1(0);
        if (epfd_ < 0) throw std::runtime_error("epoll_create1 failed");
    }

    ~EpollEventLoop() {
        if (epfd_ >= 0) ::close(epfd_);
    }

    using Handler = std::function<void(socket_t, uint32_t events)>;

    void add(socket_t sock, uint32_t events, Handler handler) {
        handlers_[sock] = std::move(handler);
        epoll_event ev{};
        ev.events   = events;
        ev.data.fd  = sock;
        epoll_ctl(epfd_, EPOLL_CTL_ADD, sock, &ev);
    }

    void remove(socket_t sock) {
        handlers_.erase(sock);
        epoll_ctl(epfd_, EPOLL_CTL_DEL, sock, nullptr);
    }

    // Run one iteration: wait up to timeout_ms
    int run_once(int timeout_ms = 10) {
        const int MAX_EVENTS = 64;
        epoll_event events[MAX_EVENTS];

        int n = epoll_wait(epfd_, events, MAX_EVENTS, timeout_ms);
        for (int i = 0; i < n; ++i) {
            auto it = handlers_.find(events[i].data.fd);
            if (it != handlers_.end()) {
                it->second(events[i].data.fd, events[i].events);
            }
        }
        return n;
    }

private:
    int  epfd_;
    std::unordered_map<socket_t, Handler> handlers_;
};

#endif

// ============================================================
// GATEWAY SIMULATION — select-based (portable)
// ============================================================

void run_gateway_demo() {
    const uint16_t PORT1 = 19100, PORT2 = 19101;

    std::atomic<bool> ready{false};
    std::atomic<int>  messages_received{0};

    // Two "exchange" listener threads
    auto run_listener = [](uint16_t port, std::atomic<bool>& ready_flag,
                           std::atomic<int>& count, const char* name)
    {
        socket_t srv = make_listener(port);
        ready_flag.store(true, std::memory_order_release);

        // Accept one connection, echo a few messages
        socket_t client = INVALID_SOCK;
        for (int i = 0; i < 100 && client == INVALID_SOCK; ++i) {
            client = ::accept(srv, nullptr, nullptr);
            if (client == INVALID_SOCK) std::this_thread::sleep_for(10ms);
        }

        if (client != INVALID_SOCK) {
            char buf[256];
            for (int j = 0; j < 3; ++j) {
                std::string msg = std::string(name) + ":ExecReport:" + std::to_string(j);
                ::send(client, msg.c_str(), static_cast<int>(msg.size()), 0);
                std::this_thread::sleep_for(5ms);
            }
            CLOSE_SOCK(client);
        }
        CLOSE_SOCK(srv);
    };

    std::atomic<bool> ready1{false}, ready2{false};
    std::thread srv1(run_listener, PORT1, std::ref(ready1), std::ref(messages_received), "ExchA");
    std::thread srv2(run_listener, PORT2, std::ref(ready2), std::ref(messages_received), "ExchB");

    while (!ready1 || !ready2) std::this_thread::sleep_for(1ms);

    // Gateway: connect to both exchanges, monitor with select
    socket_t conn1 = make_client("127.0.0.1", PORT1);
    socket_t conn2 = make_client("127.0.0.1", PORT2);

    if (conn1 == INVALID_SOCK || conn2 == INVALID_SOCK) {
        std::cout << "  Connection failed — demo requires loopback\n";
        if (conn1 != INVALID_SOCK) CLOSE_SOCK(conn1);
        if (conn2 != INVALID_SOCK) CLOSE_SOCK(conn2);
        srv1.join(); srv2.join();
        return;
    }

    std::cout << "  Gateway connected to both exchanges\n";

    SelectMonitor monitor;
    char buf[1024];

    monitor.add(conn1, [&buf, &messages_received](socket_t s) {
        int n = ::recv(s, buf, sizeof(buf) - 1, 0);
        if (n > 0) {
            buf[n] = '\0';
            std::cout << "  [ExchA] " << buf << "\n";
            messages_received.fetch_add(1);
        }
    });
    monitor.add(conn2, [&buf, &messages_received](socket_t s) {
        int n = ::recv(s, buf, sizeof(buf) - 1, 0);
        if (n > 0) {
            buf[n] = '\0';
            std::cout << "  [ExchB] " << buf << "\n";
            messages_received.fetch_add(1);
        }
    });

    // Event loop: monitor both connections simultaneously
    int iters = 0;
    while (messages_received.load() < 6 && ++iters < 200) {
        monitor.poll_once(10);  // wait up to 10ms
    }

    std::cout << "  Total messages received: " << messages_received.load() << "\n";

    CLOSE_SOCK(conn1);
    CLOSE_SOCK(conn2);
    srv1.join();
    srv2.join();
}

// ============================================================
// MAIN
// ============================================================

int main() {

#ifdef _WIN32
    WinsockInit wsa_init;
#endif

    // -------------------------------------------------------
    // SELECT API EXPLAINED
    // -------------------------------------------------------

    std::cout << "=== select() API ===\n";

    std::cout << "  select() monitors multiple fds:\n"
              << "    FD_ZERO(&rfds)           — clear the set\n"
              << "    FD_SET(sock, &rfds)      — add sock to the set\n"
              << "    select(max+1, &rfds, ...) — wait for any to be ready\n"
              << "    FD_ISSET(sock, &rfds)    — did sock have data?\n"
              << "  Limitation: max 1024 fds, O(n) scan\n";

    // -------------------------------------------------------
    // EPOLL INFO
    // -------------------------------------------------------

    std::cout << "\n=== epoll (Linux) ===\n";

#if HAS_EPOLL
    std::cout << "  epoll available (Linux)\n"
              << "  epoll_create1(0)         — create epoll instance\n"
              << "  epoll_ctl(epfd, ADD/MOD/DEL, fd, &ev) — manage fds\n"
              << "  epoll_wait(epfd, events, maxev, timeout_ms) — wait\n"
              << "  O(1) per call — only returns READY fds\n"
              << "  EPOLLIN=1 (readable), EPOLLOUT=4 (writable), EPOLLET=edge-triggered\n";

    // Demo epoll creation
    {
        int epfd = epoll_create1(0);
        if (epfd >= 0) {
            std::cout << "  epoll_create1() succeeded: epfd=" << epfd << "\n";
            ::close(epfd);
        }
    }
#else
    std::cout << "  epoll not available (not Linux)\n"
              << "  Alternatives: kqueue (macOS), IOCP (Windows)\n";
#endif

    // -------------------------------------------------------
    // GATEWAY DEMO
    // -------------------------------------------------------

    std::cout << "\n=== Gateway: select() monitors two exchanges ===\n";
    run_gateway_demo();

    // -------------------------------------------------------
    // COMPARISON TABLE
    // -------------------------------------------------------

    std::cout << "\n=== select vs poll vs epoll vs spin ===\n";

    std::cout << "  Method      Scalability  Latency    Portability  Use in HFT\n"
              << "  -------     -----------  --------   -----------  ----------\n"
              << "  select()    O(n), ≤1024  ~50µs      All platforms  Order mgmt\n"
              << "  poll()      O(n), no lim ~50µs      Linux/Mac      Order mgmt\n"
              << "  epoll()     O(1), 100K+  ~10-50µs   Linux only     Gateway\n"
              << "  spin loop   O(1), 1 sock ~100ns     All platforms  Market data\n"
              << "\n"
              << "  HFT Rule:\n"
              << "    Market data feed → dedicated spin-loop thread (< 1µs)\n"
              << "    Order management → epoll (handles many connections, ~10µs)\n"
              << "    Admin/monitoring → select or poll (simplest, low volume)\n";

    // -------------------------------------------------------
    // PATTERN: EDGE-TRIGGERED EPOLL (EPOLLET)
    // -------------------------------------------------------

    std::cout << "\n=== Edge-triggered epoll pattern ===\n";

    std::cout << "  Level-triggered (default): notified whenever data is available\n"
              << "  Edge-triggered (EPOLLET):  notified ONCE per new data arrival\n"
              << "  Edge-triggered is faster but harder: must drain ALL data in handler:\n"
              << "\n"
              << "    ev.events = EPOLLIN | EPOLLET;\n"
              << "    epoll_ctl(epfd, EPOLL_CTL_ADD, sock, &ev);\n"
              << "\n"
              << "    // In handler — MUST read all available data:\n"
              << "    while (true) {\n"
              << "        int n = recv(sock, buf, sizeof(buf), MSG_DONTWAIT);\n"
              << "        if (n == 0) { close(sock); break; }        // disconnected\n"
              << "        if (n < 0 && errno == EAGAIN) break;       // all data read\n"
              << "        if (n > 0) process(buf, n);\n"
              << "    }\n";

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Production gateway using epoll on Linux:

        class FIXGateway {
            int epfd_;
            std::unordered_map<int, ExchangeConn*> connections_;

        public:
            void add_exchange(const char* host, uint16_t port, const char* name) {
                int sock = make_client(host, port);
                set_nonblocking(sock);

                int one = 1;
                setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

                epoll_event ev{};
                ev.events  = EPOLLIN | EPOLLERR | EPOLLHUP;
                ev.data.fd = sock;
                epoll_ctl(epfd_, EPOLL_CTL_ADD, sock, &ev);

                connections_[sock] = new ExchangeConn{sock, name};
                send_fix_logon(sock, name);
            }

            void run() {
                epoll_event events[64];
                while (running_) {
                    int n = epoll_wait(epfd_, events, 64, 1);  // 1ms timeout

                    for (int i = 0; i < n; ++i) {
                        int fd = events[i].data.fd;

                        if (events[i].events & EPOLLIN) {
                            // Exchange sent us data (ExecutionReport, Heartbeat, etc.)
                            auto* conn = connections_[fd];
                            int bytes = recv(fd, recv_buf_, sizeof(recv_buf_), 0);
                            if (bytes > 0) {
                                process_fix_message(conn, recv_buf_, bytes);
                            }
                        }
                        if (events[i].events & (EPOLLERR | EPOLLHUP)) {
                            reconnect(fd);
                        }
                    }

                    // Heartbeat timeout: if any connection silent for 30s, disconnect
                    check_heartbeats();

                    // Check if we have orders to send
                    Order o;
                    while (order_queue_.pop(o)) {
                        int fd = route_to_exchange(o.symbol);
                        std::string fix_msg = build_new_order(o);
                        send(fd, fix_msg.c_str(), fix_msg.size(), 0);
                    }
                }
            }
        };
    */
}
