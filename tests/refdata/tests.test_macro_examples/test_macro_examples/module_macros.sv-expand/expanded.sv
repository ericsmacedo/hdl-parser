// Macros which create the module header or entire modules.
`include "common.svh"

`define MODULE_BEGIN(name, width) \
    module name ( \
        `CLK_RST_PORTS, \
        input  `VEC(width) d_i, \
        output `VEC(width) q_o \
    );

`define MODULE_END endmodule

// A register stage
`define STAGE(name, width) \
    `MODULE_BEGIN(name, width) \
        `FF(q_o, d_i, '0) \
    `MODULE_END

module module_macros ( 
        input  logic clk_i,  /* Clock */ 
    input  logic rst_ni  /* Reset, low active */, 
        input  logic [(8)-1:0] d_i, 
        output logic [(8)-1:0] q_o 
    );
    logic [7:0] stage;
    stage8 u_stage0 (.clk_i(clk_i), .rst_ni(rst_ni), .d_i(d_i), .q_o(stage));
    stage8 u_stage1 (.clk_i(clk_i), .rst_ni(rst_ni), .d_i(stage), .q_o(q_o));
endmodule

module stage8 ( 
        input  logic clk_i,  /* Clock */ 
    input  logic rst_ni  /* Reset, low active */, 
        input  logic [(8)-1:0] d_i, 
        output logic [(8)-1:0] q_o 
    ); 
        always_ff @(posedge clk_i or negedge rst_ni) begin 
        if (!rst_ni) begin 
            q_o <= '0; 
        end else begin 
            q_o <= d_i; 
        end 
    end 
    endmodule
module stage16 ( 
        input  logic clk_i,  /* Clock */ 
    input  logic rst_ni  /* Reset, low active */, 
        input  logic [(16)-1:0] d_i, 
        output logic [(16)-1:0] q_o 
    ); 
        always_ff @(posedge clk_i or negedge rst_ni) begin 
        if (!rst_ni) begin 
            q_o <= '0; 
        end else begin 
            q_o <= d_i; 
        end 
    end 
    endmodule
