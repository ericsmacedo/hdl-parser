// Ports defined by macros with arguments, defaults and token pasting.
`include "bus.svh"

module port_macros #(
    parameter int IN_WIDTH  = 16,
    parameter int OUT_WIDTH = 8
) (
    `CLK_RST_PORTS,
    `STREAM_PORTS(in, input, output, IN_WIDTH),
    `STREAM_PORTS(out, output, input, OUT_WIDTH),
    `STREAM_PORTS (
        aux,    // prefix
        input,
        output  // default width
    ),
    `APB_SLAVE_PORTS(cfg),
    output logic busy_o // Busy
);

endmodule
