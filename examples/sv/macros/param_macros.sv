// Parameters defined by macros, macros in defaults and dimensions, stringification.
`define WIDTH 8
`define DEPTH (1 << `WIDTH)
`define INT_PARAM(name, value) parameter int name = value
`define NAMED_PARAM(name) parameter string name``_NAME = `"name`"
`define MSG(text) `"Module: text`"
`define STD_PARAMS \
    `INT_PARAM(DATA_WIDTH, `WIDTH), \
    `INT_PARAM(ADDR_WIDTH, $clog2(`DEPTH))

module param_macros #(
    `STD_PARAMS,
    `INT_PARAM(MASK, {`WIDTH{1'b1}}),
    `NAMED_PARAM(CORE),
    parameter string MSG = `MSG(param_macros),
    parameter logic [`WIDTH-1:0] RESET_VALUE = `WIDTH'd0,
    `UNKNOWN_PARAMS(3)
) (
    input  logic [`WIDTH-1:0]      data_i,
    input  logic [ADDR_WIDTH-1:0]  addr_i [`UNKNOWN_DEPTH],
    output logic [`WIDTH*2-1:0]    data_o
);
    localparam int WORDS = `DEPTH / `WIDTH;
    localparam int UNKNOWN = `UNKNOWN_VALUE;

endmodule
