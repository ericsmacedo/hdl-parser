// Shared macros, which define ports.
`ifndef MACROS_SVH
`define MACROS_SVH

// Clock and Reset
`define CLK_RST_PORTS \
    input  logic clk_i,   /* Clock */ \
    input  logic rst_ni   /* Reset, low active */

// Valid/Ready Channel
`define STREAM_PORTS(prefix, dir_req, dir_rsp, width=8) \
    dir_req logic             prefix``_valid, \
    dir_req logic [width-1:0] prefix``_data, \
    dir_rsp logic             prefix``_ready

`endif
