// Nested includes with include guards. 'config.svh' includes 'bus.svh', which includes 'common.svh'.
`include "config.svh"
`include "bus.svh"
`include "common.svh"
`include "inc/common.svh"
`include "missing.svh"
// `include "comment.svh"

module include_chain (
    input  logic clk_i,  /* Clock */ 
    input  logic rst_ni  /* Reset, low active */,
    input logic             s_valid, 
    input logic [(32)-1:0]       s_data, 
    output logic             s_ready,
    `FROM_MISSING_FILE(x),
    output logic done_o
);
    logic [32-1:0] data_q;
    always_ff @(posedge clk_i or negedge rst_ni) begin 
        if (!rst_ni) begin 
            data_q <= '0; 
        end else begin 
            data_q <= s_data; 
        end 
    end
endmodule
