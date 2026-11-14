// Conditions and defines within macros. They are handled at the place of use.
`define PORTS \
    input  logic a_i, \
`ifdef WITH_B \
    input  logic b_i, \
`endif \
`ifdef WITH_C \
    input  logic c_i, \
`else \
    input  logic no_c_i, \
`endif \
    output logic q_o

// Enables a feature
`define ENABLE(feature) `define WITH_``feature

// A macro, which opens a condition
`define IF_B `ifdef WITH_B

// Nothing is enabled yet
module cond_in_macro_first (`PORTS);
endmodule

`ENABLE(B)

module cond_in_macro_second (
    `PORTS,
    `IF_B
    input  logic with_b_i,
    `else
    input  logic without_b_i,
    `endif
    input  logic z_i
);
endmodule

`undef WITH_B

module cond_in_macro_third (`PORTS);
endmodule
