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
    `PORT(input, plain),
    `PORT(input, wide, `DOUBLE(`DOUBLE(`W))),
    `PORT(output, array, , _o) [`W],
    `PORT(input, fn, $bits(f(1, 2)), _i),
    `PAIR(p),
    `QUAD(qa, qb),
    input logic `PREFIXED(sig),
    input logic `CONCAT(con, cat)
);

endmodule
