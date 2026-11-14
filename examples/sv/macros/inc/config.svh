// Project configuration. The defines select the variant of the design.
`ifndef CONFIG_SVH
`define CONFIG_SVH

`include "bus.svh"

// The register interface: AXI4-Lite if set, APB otherwise
`define USE_AXI

// Defaults, may be set by the build flow
`ifndef DATA_WIDTH
`define DATA_WIDTH 32
`endif
`ifndef NUM_CHANNELS
`define NUM_CHANNELS 4
`endif

// The register interface of all modules
`ifdef USE_AXI
    `define REG_BUS_PORTS(prefix) `AXIL_SLAVE_PORTS(prefix, 16)
    `define REG_BUS_NAME "axi4-lite"
`else
    `define REG_BUS_PORTS(prefix) `APB_SLAVE_PORTS(prefix, 16)
    `define REG_BUS_NAME "apb"
`endif

// Debug features depend on a define of the build flow
`ifdef DEBUG
    `define DEBUG_PORTS output logic [31:0] dbg_o,
`else
    `define DEBUG_PORTS
`endif

`endif
