// Macros which cannot be expanded: unknown, used wrong, ambiguous or recursive.
// They are reported in 'unresolved_macros', if they are located in the module header.
`define TWO_ARGS(a, b) input logic a, input logic b
`define LOOP_A input logic loop_a_i, `LOOP_B
`define LOOP_B input logic loop_b_i, `LOOP_A

`ifdef VARIANT_X
    `define AMBIGUOUS input logic x_i
`else
    `define AMBIGUOUS input logic y_i
`endif

module unresolved #(
    parameter int A = 1,
    `UNKNOWN_PARAMS,
    `UNKNOWN_PARAMS_ARGS(A, f(1, 2), "a,b")
) (
    `UNKNOWN_PORTS,
`ifdef VARIANT_X
    `UNKNOWN_IN_IFDEF(x),
`endif
    `TWO_ARGS(only_one),
    `TWO_ARGS(one, two, three),
    `TWO_ARGS,
    input logic ok_a_i, input logic ok_b_i,
    `AMBIGUOUS,
    input logic loop_a_i, input logic loop_b_i, `LOOP_A,
    input  `UNKNOWN_TYPE typed_i,
    input  logic [`UNKNOWN_WIDTH-1:0] sized_i,
    output logic q_o
);
    `UNKNOWN_BODY(q_o)
endmodule
