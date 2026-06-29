// ============================================================
// L46: Network Sockets: TCP and UDP
// ============================================================
// WHAT: BSD sockets API for creating TCP connections and UDP
//       endpoints. TCP: reliable, ordered, used for FIX order
//       entry. UDP: unreliable, low-latency, used for market
//       data (ITCH, OPRA, CME Globex MDP 3.0).
// WHY (TRADING): Every piece of market data and every order
//   flows through a socket. Tuning the socket matters:
//   TCP_NODELAY prevents Nagle's algorithm from batching your
//   small FIX order messages into larger TCP segments — that
//   batching adds 1-40ms of latency per order.
//   SO_RCVBUF/SO_SNDBUF: increase kernel receive buffer so that
//   a burst of UDP multicast packets doesn't drop due to buffer
//   overflow while your thread is busy processing.
//   MSG_DONTWAIT: non-blocking recv allows the hot-path spin
//   loop to check for packets without ever blocking.
// PHASE: Low-Latency Systems
// ============================================================

/*
  CONCEPT OVERVIEW:

  SOCKET LIFECYCLE:
    TCP client: socket() → connect() → send()/recv() → close()
    TCP server: socket() → bind() → listen() → accept() → send()/recv() → close()
    UDP sender: socket() → sendto() → close()
    UDP receiver: socket() → bind() → recvfrom() → close()

  KEY SYSTEM CALLS:
    socket(AF_INET, SOCK_STREAM, 0)  — create TCP socket
    socket(AF_INET, SOCK_DGRAM, 0)   — create UDP socket
    connect(sock, &addr, addrlen)    — TCP: establish connection
    bind(sock, &addr, addrlen)       — associate socket with local address
    listen(sock, backlog)            — TCP: start accepting connections
    accept(sock, &client, &len)      — TCP: accept one connection
    send(sock, buf, len, flags)      — send data
    recv(sock, buf, len, flags)      — receive data
    sendto(sock, buf, len, flags, &dst, dstlen) — UDP send
    recvfrom(sock, buf, len, flags, &src, &srclen) — UDP receive
    close(sock) / closesocket(sock)  — close the socket

  CRITICAL SOCKET OPTIONS FOR HFT:
    TCP_NODELAY:   Disable Nagle's algorithm. Without this, TCP
                   buffers small sends and waits for ACKs before
                   sending more — adds 1-40ms per order!
                   setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one))

    SO_RCVBUF:     Increase kernel receive buffer. Default ~128KB.
                   Set to 4-16MB for high-rate market data feeds.
                   setsockopt(sock, SOL_SOCKET, SO_RCVBUF, &size, sizeof(size))

    SO_SNDBUF:     Increase kernel send buffer for burst sending.

    SO_REUSEADDR:  Allow binding to a port immediately after a crash
                   (avoids TIME_WAIT state locking the port for 2 minutes).

    SO_RCVTIMEO:   Set receive timeout (avoids blocking forever).

    IP_TOS:        Set IP TOS/DSCP for QoS priority on the network.

  NON-BLOCKING SOCKETS:
    fcntl(sock, F_SETFL, O_NONBLOCK)   — Linux: make non-blocking
    ioctlsocket(sock, FIONBIO, &mode)  — Windows
    recv with MSG_DONTWAIT flag        — non-blocking single recv call
    When no data: recv returns -1 with errno == EAGAIN (Linux) or
    GetLastError() == WSAEWOULDBLOCK (Windows).
    Use in: hot-path spin loop (poll for data without blocking).

  BLOCKING vs NON-BLOCKING:
    Blocking recv: thread sleeps until data arrives (OS wakes it up).
                   Wakeup latency: 50-200µs → too slow for HFT.
    Non-blocking recv: returns immediately (EAGAIN if no data).
                   Combined with spin loop: < 1µs response latency.

  ADDRESS STRUCTURES:
    struct sockaddr_in {
        sa_family_t sin_family;   // AF_INET
        uint16_t    sin_port;     // htons(port)
        struct in_addr sin_addr;  // inet_addr("1.2.3.4") or INADDR_ANY
    };

  BYTE ORDER:
    htons(x): host to network byte order for port (16-bit)
    htonl(x): host to network byte order for IP (32-bit)
    ntohs(x): network to host for port
    ntohl(x): network to host for IP
    Network is big-endian; x86 is little-endian — always convert.

  TRADING USE CASE:
    TCP: FIX engine connects to exchange FIX server.
         Send NewOrderSingle → receive ExecutionReport.
         Must be TCP (ordered, reliable, retransmits).
    UDP: NASDAQ ITCH market data arrives as multicast UDP.
         Packets may arrive out of order or be dropped.
         Feed handler detects gaps and requests retransmission.

  COMMON MISTAKES:
    - Forgetting TCP_NODELAY → orders take 1-40ms extra per send
    - Using blocking recv in a hot path → thread sleeps on every tick
    - recv/send return values < requested: must loop until all bytes sent/received
    - Ignoring errno on failure: check errno to distinguish EAGAIN from real errors
    - Not setting SO_RCVBUF large enough → packet loss during burst data
    - Mixing htons/htonl: ports are 16-bit (htons), IPs are 32-bit (htonl)
*/

#include <iostream>
#include <cstring>
#include <cstdint>
#include <string>
#include <stdexcept>
#include <vector>
#include <chrono>

// Platform-specific socket headers
#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  pragma comment(lib, "Ws2_32.lib")
   using socket_t = SOCKET;
   static const socket_t INVALID_SOCK = INVALID_SOCKET;
#  define SOCK_ERR WSAGetLastError()
#  define CLOSE_SOCK(s) closesocket(s)
#  define EAGAIN_ERR WSAEWOULDBLOCK
#else
#  include <sys/socket.h>
#  include <netinet/in.h>
#  include <netinet/tcp.h>  // TCP_NODELAY
#  include <arpa/inet.h>
#  include <unistd.h>
#  include <fcntl.h>
#  include <errno.h>
   using socket_t = int;
   static const socket_t INVALID_SOCK = -1;
#  define SOCK_ERR errno
#  define CLOSE_SOCK(s) ::close(s)
#  define EAGAIN_ERR EAGAIN
#endif

// ============================================================
// WINSOCK INIT HELPER
// ============================================================

#ifdef _WIN32
struct WinsockInit {
    WinsockInit() {
        WSADATA wsa{};
        if (WSAStartup(MAKEWORD(2,2), &wsa) != 0) {
            throw std::runtime_error("WSAStartup failed");
        }
    }
    ~WinsockInit() { WSACleanup(); }
};
#endif

// ============================================================
// SOCKET UTILITIES
// ============================================================

// Create a TCP socket and apply HFT-critical options
socket_t create_tcp_socket() {
    socket_t sock = ::socket(AF_INET, SOCK_STREAM, 0);
    if (sock == INVALID_SOCK) {
        throw std::runtime_error("socket() failed: " + std::to_string(SOCK_ERR));
    }
    return sock;
}

// Create a UDP socket
socket_t create_udp_socket() {
    socket_t sock = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == INVALID_SOCK) {
        throw std::runtime_error("socket() failed: " + std::to_string(SOCK_ERR));
    }
    return sock;
}

// Apply HFT socket options to an existing socket
bool apply_hft_options(socket_t sock, bool is_tcp) {
    bool ok = true;
    int one = 1;
    int rcvbuf = 4 * 1024 * 1024;   // 4MB receive buffer
    int sndbuf = 1 * 1024 * 1024;   // 1MB send buffer

    if (is_tcp) {
        // CRITICAL: disable Nagle's algorithm
        // Without this, TCP buffers small sends for up to 40ms
        if (setsockopt(sock, IPPROTO_TCP, TCP_NODELAY,
                       (const char*)&one, sizeof(one)) < 0) {
            std::cerr << "  WARNING: TCP_NODELAY failed\n";
            ok = false;
        }
    }

    // Increase receive buffer (prevents packet loss during burst)
    if (setsockopt(sock, SOL_SOCKET, SO_RCVBUF,
                   (const char*)&rcvbuf, sizeof(rcvbuf)) < 0) {
        std::cerr << "  WARNING: SO_RCVBUF failed\n";
        ok = false;
    }

    // Increase send buffer
    if (setsockopt(sock, SOL_SOCKET, SO_SNDBUF,
                   (const char*)&sndbuf, sizeof(sndbuf)) < 0) {
        std::cerr << "  WARNING: SO_SNDBUF failed\n";
        ok = false;
    }

    // Allow reuse of address (avoid "Address already in use" after crash)
    if (setsockopt(sock, SOL_SOCKET, SO_REUSEADDR,
                   (const char*)&one, sizeof(one)) < 0) {
        std::cerr << "  WARNING: SO_REUSEADDR failed\n";
    }

    return ok;
}

// Make a socket non-blocking
bool set_nonblocking(socket_t sock) {
#ifdef _WIN32
    u_long mode = 1;
    return ioctlsocket(sock, FIONBIO, &mode) == 0;
#else
    int flags = fcntl(sock, F_GETFL, 0);
    if (flags < 0) return false;
    return fcntl(sock, F_SETFL, flags | O_NONBLOCK) == 0;
#endif
}

// Get actual buffer size after setsockopt (OS may give you less)
int get_sockopt_int(socket_t sock, int level, int optname) {
    int val = 0;
    socklen_t len = sizeof(val);
    getsockopt(sock, level, optname, (char*)&val, &len);
    return val;
}

// Build sockaddr_in from host string and port
sockaddr_in make_addr(const std::string& host, uint16_t port) {
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(port);
    if (host == "0.0.0.0" || host.empty()) {
        addr.sin_addr.s_addr = INADDR_ANY;
    } else {
        inet_pton(AF_INET, host.c_str(), &addr.sin_addr);
    }
    return addr;
}

// ============================================================
// ECHO SERVER/CLIENT DEMO (loopback)
// ============================================================

// Mini TCP echo server: accepts one connection, echoes all data back
void run_echo_server(uint16_t port, std::atomic<bool>& server_ready) {
#ifdef _WIN32
    WinsockInit wsa_init;
#endif
    socket_t srv = create_tcp_socket();
    apply_hft_options(srv, true);

    auto addr = make_addr("0.0.0.0", port);
    if (::bind(srv, (sockaddr*)&addr, sizeof(addr)) < 0) {
        std::cerr << "  [Server] bind failed: " << SOCK_ERR << "\n";
        CLOSE_SOCK(srv);
        return;
    }
    ::listen(srv, 1);
    server_ready.store(true);

    socket_t client = ::accept(srv, nullptr, nullptr);
    if (client == INVALID_SOCK) {
        CLOSE_SOCK(srv);
        return;
    }
    apply_hft_options(client, true);

    char buf[4096];
    int bytes;
    while ((bytes = ::recv(client, buf, sizeof(buf), 0)) > 0) {
        ::send(client, buf, bytes, 0);  // echo back
    }

    CLOSE_SOCK(client);
    CLOSE_SOCK(srv);
}

// ============================================================
// FIX MESSAGE SIMULATION
// ============================================================

// Simulate sending a FIX NewOrderSingle over TCP
struct FIXOrder {
    int64_t     price;
    int32_t     qty;
    bool        is_buy;
    char        symbol[8];
    uint64_t    order_id;
};

// Build a simplified FIX NewOrderSingle string
std::string build_fix_order(const FIXOrder& o) {
    std::string msg;
    msg += "8=FIX.4.2\x01";
    msg += "35=D\x01";  // MsgType = NewOrderSingle
    msg += "49=CLIENT\x01";
    msg += "56=EXCHANGE\x01";
    msg += "11="; msg += std::to_string(o.order_id); msg += "\x01";  // ClOrdID
    msg += "55="; msg += o.symbol; msg += "\x01";                     // Symbol
    msg += "54="; msg += (o.is_buy ? "1" : "2"); msg += "\x01";       // Side
    msg += "38="; msg += std::to_string(o.qty); msg += "\x01";        // OrderQty
    msg += "44="; msg += std::to_string(o.price / 10000.0); msg += "\x01"; // Price
    msg += "40=2\x01";  // OrdType = Limit
    return msg;
}

// ============================================================
// UDP RECEIVE LOOP SIMULATION
// ============================================================

// In production: this runs in a tight spin loop on a pinned core.
// Here we demonstrate the pattern with a simple loopback test.
void demo_udp_pattern() {
    std::cout << "\n  UDP receive pattern (concept — no actual network):\n";
    std::cout << "    // Create UDP socket, bind to multicast group\n";
    std::cout << "    // In hot-path spin loop:\n";
    std::cout << "    while(running) {\n";
    std::cout << "        int bytes = recvfrom(sock, buf, sizeof(buf), MSG_DONTWAIT, ...);\n";
    std::cout << "        if (bytes > 0) { process_packet(buf, bytes); }\n";
    std::cout << "        else { _mm_pause(); }  // no packet — spin with pause\n";
    std::cout << "    }\n";
}

// ============================================================
// MAIN
// ============================================================

int main() {

#ifdef _WIN32
    WinsockInit wsa_init;
#endif

    // -------------------------------------------------------
    // SOCKET CREATION AND OPTIONS
    // -------------------------------------------------------

    std::cout << "=== Socket creation and HFT options ===\n";

    {
        socket_t tcp_sock = create_tcp_socket();
        std::cout << "  TCP socket created: fd=" << tcp_sock << "\n";

        apply_hft_options(tcp_sock, true);
        std::cout << "  TCP_NODELAY set (Nagle's disabled)\n";

        // Verify actual buffer sizes (OS may cap them)
        int rcvbuf = get_sockopt_int(tcp_sock, SOL_SOCKET, SO_RCVBUF);
        int sndbuf = get_sockopt_int(tcp_sock, SOL_SOCKET, SO_SNDBUF);
        std::cout << "  Actual SO_RCVBUF: " << rcvbuf << " bytes\n";
        std::cout << "  Actual SO_SNDBUF: " << sndbuf << " bytes\n";
        std::cout << "  (OS may double what you requested, or cap it)\n";

        set_nonblocking(tcp_sock);
        std::cout << "  Non-blocking mode set\n";

        CLOSE_SOCK(tcp_sock);
    }

    {
        socket_t udp_sock = create_udp_socket();
        std::cout << "\n  UDP socket created: fd=" << udp_sock << "\n";
        apply_hft_options(udp_sock, false);
        int rcvbuf = get_sockopt_int(udp_sock, SOL_SOCKET, SO_RCVBUF);
        std::cout << "  UDP SO_RCVBUF: " << rcvbuf << " bytes\n";
        CLOSE_SOCK(udp_sock);
    }

    // -------------------------------------------------------
    // FIX ORDER CONSTRUCTION
    // -------------------------------------------------------

    std::cout << "\n=== FIX order message ===\n";

    {
        FIXOrder order{};
        order.price    = 1825500;   // $182.55
        order.qty      = 100;
        order.is_buy   = true;
        std::memcpy(order.symbol, "AAPL\0\0\0\0", 8);
        order.order_id = 1001;

        std::string fix_msg = build_fix_order(order);
        // Replace SOH (\x01) with | for readable output
        std::string readable = fix_msg;
        for (char& c : readable) if (c == '\x01') c = '|';
        std::cout << "  FIX message (" << fix_msg.size() << " bytes):\n  " << readable << "\n";
        std::cout << "  TCP_NODELAY ensures this is sent immediately (no Nagle buffering)\n";
    }

    // -------------------------------------------------------
    // LOOPBACK TCP TEST
    // -------------------------------------------------------

    std::cout << "\n=== TCP loopback echo test ===\n";

    {
        const uint16_t TEST_PORT = 19000;
        std::atomic<bool> server_ready{false};

        // Run echo server in background thread
        std::thread server_thread([TEST_PORT, &server_ready]() {
            run_echo_server(TEST_PORT, server_ready);
        });

        // Wait for server to be ready
        while (!server_ready.load(std::memory_order_acquire)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }

        // Client: connect, send FIX order, measure round-trip latency
        socket_t client = create_tcp_socket();
        apply_hft_options(client, true);

        auto addr = make_addr("127.0.0.1", TEST_PORT);
        if (::connect(client, (sockaddr*)&addr, sizeof(addr)) == 0) {
            std::cout << "  Connected to loopback echo server\n";

            const char* msg = "8=FIX.4.2\x01" "35=D\x01" "55=AAPL\x01" "38=100\x01";
            int msg_len = static_cast<int>(strlen(msg));

            // Measure round-trip latency
            auto t0 = std::chrono::steady_clock::now();
            ::send(client, msg, msg_len, 0);

            char buf[256];
            int bytes = ::recv(client, buf, sizeof(buf), 0);
            auto t1 = std::chrono::steady_clock::now();

            auto rtt_us = std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count();
            std::cout << "  Sent " << msg_len << " bytes, received " << bytes << " bytes\n";
            std::cout << "  Loopback RTT: " << rtt_us << "µs\n";
            std::cout << "  (loopback has kernel overhead; wire RTT to exchange ≈ 100-500µs)\n";
        } else {
            std::cout << "  Connect failed (may not have server running)\n";
        }

        CLOSE_SOCK(client);
        server_thread.join();
    }

    // -------------------------------------------------------
    // UDP PATTERN
    // -------------------------------------------------------

    demo_udp_pattern();

    // -------------------------------------------------------
    // BYTE ORDER DEMO
    // -------------------------------------------------------

    std::cout << "\n=== Byte order (htons/htonl) ===\n";

    {
        uint16_t port = 4001;
        uint32_t ip   = 0xC0A80001;  // 192.168.0.1

        std::cout << "  Port 4001 in host order: 0x" << std::hex << port << "\n";
        std::cout << "  Port 4001 in network order: 0x" << std::hex << htons(port) << "\n";
        std::cout << std::dec;
        std::cout << "  htonl(0xC0A80001) = 0x" << std::hex << htonl(ip) << std::dec << "\n";
        std::cout << "  Always call htons(port) and htonl/inet_pton(ip) when filling sockaddr_in\n";
    }

    return 0;

    /*
      TRADING CONTEXT EXAMPLE:
      Connecting to an exchange FIX gateway:

        // 1. Create and configure socket
        socket_t sock = socket(AF_INET, SOCK_STREAM, 0);
        int one = 1;
        setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));  // CRITICAL
        int bufsize = 8 * 1024 * 1024;
        setsockopt(sock, SOL_SOCKET, SO_RCVBUF, &bufsize, sizeof(bufsize));

        // 2. Connect to exchange FIX gateway
        sockaddr_in addr = make_addr("10.0.1.5", 4001);
        connect(sock, (sockaddr*)&addr, sizeof(addr));

        // 3. Send FIX Logon (35=A)
        std::string logon = build_fix_logon(sender_id, target_id, heartbeat_interval);
        send(sock, logon.c_str(), logon.size(), 0);

        // 4. Receive Logon acknowledgment (loop until all bytes received)
        char buf[65536];
        int total = 0;
        while (total < expected_len) {
            int n = recv(sock, buf + total, sizeof(buf) - total, 0);
            if (n <= 0) break;
            total += n;
        }

        // 5. Enter trading loop — non-blocking recv
        set_nonblocking(sock);
        while (running) {
            // Check for incoming ExecutionReport (fill/reject)
            int n = recv(sock, buf, sizeof(buf), MSG_DONTWAIT);
            if (n > 0) {
                process_execution_report(buf, n);
            } else if (SOCK_ERR != EAGAIN_ERR) {
                // Real error — attempt reconnect
                break;
            }
            // Check if we have an order to send
            Order o;
            if (order_queue_.pop(o)) {
                std::string fix_order = build_fix_new_order(o);
                send(sock, fix_order.c_str(), fix_order.size(), 0);
                // TCP_NODELAY ensures this goes on the wire immediately
            }
            _mm_pause();
        }
    */
}
