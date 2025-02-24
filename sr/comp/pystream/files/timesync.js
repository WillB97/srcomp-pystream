// Get clock offset, network and server latency
// To configure: source this file, call configure_timesync with a websocket
// handle and include the following in the onmessage handler:

// const msg = JSON.parse(event.data);
// if (msg.type == "timesync") {
//     process_timesync(msg);
// }

// The current values can be accessed from the current_latencies dictionary

var current_latencies = {
    time_error: null,
    server_latency: null,
    network_latency: null
};
var timesync_ws = null;
var timesync_interval = null;


function configure_timesync(ws, interval=1000) {
    timesync_ws = ws;
    if (timesync_interval !== null) {
        clearInterval(timesync_interval);
    }
    timesync_interval = setInterval(do_timesync, interval);
    do_timesync();
}
function do_timesync() {
    if (timesync_ws !== null && timesync_ws.readyState != 1) {
        return;
    }
    timesync_ws.send(JSON.stringify({ type: "timesync", sent_ms: Date.now() }));
}

function process_timesync(msg) {
    const d = Date.now()
    function decay_filter(new_val, prev_val) {
        if (prev_val !== null) {
            return 0.9 * prev_val + 0.1 * new_val;
        } else {
            return new_val;
        }
    }
    function smooth_latencies(raw_latency) {
        current_latencies = {
            time_error: decay_filter(raw_latency.time_error, current_latencies.time_error),
            server_latency: decay_filter(raw_latency.server_latency, current_latencies.server_latency),
            network_latency: decay_filter(raw_latency.network_latency, current_latencies.network_latency)
        };
        return current_latencies;
    }

    const client_sent_ms = msg.sent_ms;
    const server_recv_ms = msg.server_recv * 1000;
    const server_sent_ms = msg.server_sent * 1000;
    const client_recv_ms = d;

    const ul_diff = server_recv_ms - client_sent_ms;
    const dl_diff = client_recv_ms - server_sent_ms;
    const client_mid_time = (client_recv_ms + client_sent_ms) / 2
    const server_mid_time = (server_recv_ms + server_sent_ms) / 2

    latencies = {
        rtt: client_recv_ms - client_sent_ms,
        time_error: client_mid_time - server_mid_time,
        server_latency: server_sent_ms - server_recv_ms,
        network_latency: (ul_diff + dl_diff) / 2
    };
    current_latencies = smooth_latencies(latencies);
}
