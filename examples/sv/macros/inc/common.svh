// Macros shared by all modules: clock, reset and register helpers.
`ifndef COMMON_SVH
`define COMMON_SVH

// Clock and Reset
`define CLK_RST_PORTS \
    input  logic clk_i,  /* Clock */ \
    input  logic rst_ni  /* Reset, low active */

// Connect clock and reset by name
`define CLK_RST_CON .clk_i(clk_i), .rst_ni(rst_ni)

// Vector type
`define VEC(width) logic [(width)-1:0]

// Register with asynchronous reset
`define FF(q, d, rst_val) \
    always_ff @(posedge clk_i or negedge rst_ni) begin \
        if (!rst_ni) begin \
            q <= rst_val; \
        end else begin \
            q <= d; \
        end \
    end

`endif
