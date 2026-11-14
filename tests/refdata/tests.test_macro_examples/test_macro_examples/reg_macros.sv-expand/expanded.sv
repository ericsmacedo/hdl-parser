// Macros in the module body: registers, generate blocks and assertions.
`include "common.svh"

`define ASSERT(name, prop) name: assert property (@(posedge clk_i) disable iff (!rst_ni) (prop));
`define REG(name, width, rst_val='0) \
    logic [width-1:0] name``_d, name``_q; \
    `FF(name``_q, name``_d, rst_val)

module reg_macros #(
    parameter int WIDTH = 8,
    parameter int STAGES = 3
) (
    input  logic clk_i,  /* Clock */ 
    input  logic rst_ni  /* Reset, low active */,
    input  logic [WIDTH-1:0] d_i,
    output logic [WIDTH-1:0] q_o
);
    logic [WIDTH-1:0] first_d, first_q; 
    always_ff @(posedge clk_i or negedge rst_ni) begin 
        if (!rst_ni) begin 
            first_q <= '0; 
        end else begin 
            first_q <= first_d; 
        end 
    end
    logic [4-1:0] count_d, count_q; 
    always_ff @(posedge clk_i or negedge rst_ni) begin 
        if (!rst_ni) begin 
            count_q <= 4'd1; 
        end else begin 
            count_q <= count_d; 
        end 
    end

    assign first_d = d_i;
    assign count_d = count_q + 4'd1;

    for (genvar i = 0; i < STAGES; i++) begin : gen_stage
        logic [WIDTH-1:0] stage_d, stage_q; 
    always_ff @(posedge clk_i or negedge rst_ni) begin 
        if (!rst_ni) begin 
            stage_q <= '0; 
        end else begin 
            stage_q <= stage_d; 
        end 
    end
        delay #(.WIDTH(WIDTH)) u_delay (.clk_i(clk_i), .rst_ni(rst_ni), .d_i(stage_q), .q_o());
    end

    CountNotZero_A: assert property (@(posedge clk_i) disable iff (!rst_ni) (count_q != 4'd0));
    Stable_A: assert property (@(posedge clk_i) disable iff (!rst_ni) ($stable(d_i) |-> $stable(first_d)));

    assign q_o = first_q;
endmodule
