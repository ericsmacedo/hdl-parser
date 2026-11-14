// Macros as port type and macros which create type definitions.
`define DATA_T logic [7:0]
`define BUS_T(width) logic [width-1:0]
`define STRUCT_T(name, width) \
    typedef struct packed { \
        logic             valid; \
        logic [width-1:0] data; \
    } name;

module type_macros #(
    parameter type T = logic [7:0]
) (
    input  logic [7:0]      data_i,
    input  logic [16-1:0]   bus_i,
    input  logic [4-1:0]    nibbles_i [8],
    input  `EXTERNAL_T  ext_i,
    input  `EXTERNAL_T(3) ext_arg_i,
    output T            data_o
);
    typedef struct packed { 
        logic             valid; 
        logic [8-1:0] data; 
    } req_t;
    typedef struct packed { 
        logic             valid; 
        logic [16-1:0] data; 
    } rsp_t;
    req_t req;
    rsp_t rsp;
endmodule
