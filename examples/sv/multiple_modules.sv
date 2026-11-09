// Several modules in one file, with packages, imports and labels
package my_pkg;
  typedef logic [7:0] byte_t;
endpackage

module mod_a
  import my_pkg::*;
(
  input  byte_t a,
  output byte_t b
);
  assign b = a;
endmodule : mod_a

module mod_b (input logic x, output logic y);
  mod_a u_a (.a(x), .b(y));
endmodule

module mod_c;
endmodule
