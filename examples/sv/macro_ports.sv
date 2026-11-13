// Macros defining parameters and ports in the module header.
//
// `CLK_RST_PORTS and `STREAM_PORTS are defined in 'macros.svh':
//
//     hdl-parser info --macro-file examples/sv/macros.svh examples/sv/macro_ports.sv

`include "macros.svh"

`define WIDTH_PARAM(name, value) parameter int name = value

module macro_ports #(
    `WIDTH_PARAM(IN_WIDTH, 16),
    `WIDTH_PARAM(OUT_WIDTH, 8)
) (
    `CLK_RST_PORTS,
    `STREAM_PORTS(in, input, output, IN_WIDTH),
    `STREAM_PORTS(out, output, input),
    output logic busy_o // Busy
);

endmodule
