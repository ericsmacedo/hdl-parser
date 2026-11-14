// Nested includes with include guards. 'config.svh' includes 'bus.svh', which includes 'common.svh'.
`include "config.svh"
`include "bus.svh"
`include "common.svh"
`include "inc/common.svh"
`include "missing.svh"
// `include "comment.svh"

module include_chain (
    `CLK_RST_PORTS,
    `STREAM_PORTS(s, input, output, `DATA_WIDTH),
    `FROM_MISSING_FILE(x),
    output logic done_o
);
    logic [`DATA_WIDTH-1:0] data_q;
    `FF(data_q, s_data, '0)
endmodule
