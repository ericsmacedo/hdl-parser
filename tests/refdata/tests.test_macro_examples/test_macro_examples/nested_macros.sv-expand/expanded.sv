// Macros using macros, macros as arguments, default and empty arguments.
`define W 4
`define DOUBLE(x) (2*(x))
`define VEC(width) logic [width-1:0]
`define PORT(dir, name, width=`W, suffix=) dir `VEC(width) name``suffix
`define PAIR(name, width=`W) \
    `PORT(input, name, width, _i), \
    `PORT(output, name, width, _o)
`define QUAD(a, b) `PAIR(a), `PAIR(b, `DOUBLE(`W))
`define CONCAT(a, b) a``b
`define PREFIXED(name) `CONCAT(pre_, name)

module nested_macros (
    input logic [4-1:0] plain,
    input logic [(2*((2*(4))))-1:0] wide,
    output logic [4-1:0] array_o [4],
    input logic [$bits(f(1, 2))-1:0] fn_i,
    input logic [4-1:0] p_i, 
    output logic [4-1:0] p_o,
    input logic [4-1:0] qa_i, 
    output logic [4-1:0] qa_o, input logic [(2*(4))-1:0] qb_i, 
    output logic [(2*(4))-1:0] qb_o,
    input logic pre_sig,
    input logic concat
);

endmodule
