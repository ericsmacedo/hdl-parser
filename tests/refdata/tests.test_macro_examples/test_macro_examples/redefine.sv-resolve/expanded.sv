// Macros are processed in order: redefinition, `undef and local macros.
`define WIDTH 8
`define PORTS input logic [`WIDTH-1:0] a_i

module redefine_first (input logic [8-1:0] a_i, output logic [8-1:0] q_o);
endmodule

`undef WIDTH
`define WIDTH 16
`define PORTS input logic [`WIDTH-1:0] a_i, input logic [`WIDTH-1:0] b_i

module redefine_second (input logic [16-1:0] a_i, input logic [16-1:0] b_i, output logic [16-1:0] q_o);
endmodule

`undef PORTS
`undef WIDTH

// both macros are unknown now
module redefine_third (`PORTS, output logic [`WIDTH-1:0] q_o);
    // a macro local to this module
    `define LOCAL_SIG(name) logic name;
    logic x;
    `undef LOCAL_SIG
endmodule

// defined behind its use
module redefine_fourth (`LATE);
endmodule
`define LATE input logic late_i
