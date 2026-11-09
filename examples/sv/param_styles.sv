// Parameter declaration styles
module param_styles #(
  parameter               P_IMPLICIT = 1,
  parameter int           P_INT      = 32'd10,   // sized literal
  parameter integer       P_A = 1, P_B = 2,      // multiple names
  parameter logic [7:0]   P_VEC      = 8'hFF,
  parameter real          P_REAL     = 1.5,
  parameter string        P_STR      = "hello, world",
  parameter int           P_EXPR     = (P_A + P_B) * 2,
  parameter logic [3:0]   P_CONCAT   = {2'b10, 2'b01},
  parameter int           P_ARR [2]  = '{1, 2},
  parameter int           P_FUNC     = $clog2(P_INT)
) (
  input  logic [P_INT-1:0] d,
  output logic [P_INT-1:0] q
);
  localparam int L_WIDTH = P_INT * 2;
  localparam     L_MSG   = "local";
  parameter      P_BODY  = 3;   // body parameter
endmodule
