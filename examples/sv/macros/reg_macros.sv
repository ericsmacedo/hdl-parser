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
    `CLK_RST_PORTS,
    input  logic [WIDTH-1:0] d_i,
    output logic [WIDTH-1:0] q_o
);
    `REG(first, WIDTH)
    `REG(count, 4, 4'd1)

    assign first_d = d_i;
    assign count_d = count_q + 4'd1;

    for (genvar i = 0; i < STAGES; i++) begin : gen_stage
        `REG(stage, WIDTH)
        delay #(.WIDTH(WIDTH)) u_delay (`CLK_RST_CON, .d_i(stage_q), .q_o());
    end

    `ASSERT(CountNotZero_A, count_q != 4'd0)
    `ASSERT(Stable_A, $stable(d_i) |-> $stable(first_d))

    assign q_o = first_q;
endmodule
