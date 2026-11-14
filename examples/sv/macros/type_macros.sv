// Macros as port type and macros which create type definitions.
`define DATA_T logic [7:0]
`define BUS_T(width) logic [width-1:0]
`define STRUCT_T(name, width) \
    typedef struct packed { \
        logic             valid; \
        logic [width-1:0] data; \
    } name;

module type_macros #(
    parameter type T = `DATA_T
) (
    input  `DATA_T      data_i,
    input  `BUS_T(16)   bus_i,
    input  `BUS_T(4)    nibbles_i [8],
    input  `EXTERNAL_T  ext_i,
    input  `EXTERNAL_T(3) ext_arg_i,
    output T            data_o
);
    `STRUCT_T(req_t, 8)
    `STRUCT_T(rsp_t, 16)
    req_t req;
    rsp_t rsp;
endmodule
