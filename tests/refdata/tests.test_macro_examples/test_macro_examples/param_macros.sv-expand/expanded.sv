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
    parameter int DATA_WIDTH = 8, 
    parameter int ADDR_WIDTH = $clog2((1 << 8)),
    parameter int MASK = {8{1'b1}},
    parameter string CORE_NAME = "CORE",
    parameter string MSG = "Module: param_macros",
    parameter logic [8-1:0] RESET_VALUE = 8'd0,
    `UNKNOWN_PARAMS(3)
) (
    input  logic [8-1:0]      data_i,
    input  logic [ADDR_WIDTH-1:0]  addr_i [`UNKNOWN_DEPTH],
    output logic [8*2-1:0]    data_o
);
    localparam int WORDS = (1 << 8) / 8;
    localparam int UNKNOWN = `UNKNOWN_VALUE;

endmodule
