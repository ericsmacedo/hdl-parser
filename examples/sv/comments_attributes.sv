/*
 * File header comment
 */
module comments_attributes /* after name */ #(
  // comment before parameter
  parameter int WIDTH = 8 /* inline block */
) (
  /* block comment before port */
  input  logic             clk,   // line comment
  (* keep = "true" *)
  input  logic [WIDTH-1:0] d,     /* block comment after port */
  // multi-line
  // comment
  output logic [WIDTH-1:0] q
);
  // input and output inside comments must be ignored: input fake;
  /* output also_fake; */
  assign q = d;
endmodule
