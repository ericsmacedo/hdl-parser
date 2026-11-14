// Bus interfaces as port lists. The prefix is pasted to every signal name.
`ifndef BUS_SVH
`define BUS_SVH

`include "common.svh"

// Valid/Ready stream. 'dir_req' is the direction of valid and data.
`define STREAM_PORTS(prefix, dir_req, dir_rsp, width=8) \
    dir_req logic             prefix``_valid, \
    dir_req `VEC(width)       prefix``_data, \
    dir_rsp logic             prefix``_ready

// APB slave
`define APB_SLAVE_PORTS(prefix, addr_width=12) \
    input  logic                  prefix``_psel_i,    /* Select */ \
    input  logic                  prefix``_penable_i, /* Enable */ \
    input  logic                  prefix``_pwrite_i,  /* Write */ \
    input  `VEC(addr_width)       prefix``_paddr_i,   /* Address */ \
    input  logic [31:0]           prefix``_pwdata_i,  /* Write Data */ \
    output logic [31:0]           prefix``_prdata_o,  /* Read Data */ \
    output logic                  prefix``_pready_o   /* Ready */

// AXI4-Lite slave, write channels only
`define AXIL_SLAVE_PORTS(prefix, addr_width=12) \
    input  logic                  prefix``_awvalid_i, \
    output logic                  prefix``_awready_o, \
    input  `VEC(addr_width)       prefix``_awaddr_i, \
    input  logic                  prefix``_wvalid_i, \
    output logic                  prefix``_wready_o, \
    input  logic [31:0]           prefix``_wdata_i, \
    output logic                  prefix``_bvalid_o, \
    input  logic                  prefix``_bready_i

// Connect all signals of an APB slave by name
`define APB_CON(prefix) \
    .prefix``_psel_i   (prefix``_psel), \
    .prefix``_penable_i(prefix``_penable), \
    .prefix``_pwrite_i (prefix``_pwrite), \
    .prefix``_paddr_i  (prefix``_paddr), \
    .prefix``_pwdata_i (prefix``_pwdata), \
    .prefix``_prdata_o (prefix``_prdata), \
    .prefix``_pready_o (prefix``_pready)

`endif
