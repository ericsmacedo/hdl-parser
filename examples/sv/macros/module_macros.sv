// Macros which create the module header or entire modules.
`include "common.svh"

`define MODULE_BEGIN(name, width) \
    module name ( \
        `CLK_RST_PORTS, \
        input  `VEC(width) d_i, \
        output `VEC(width) q_o \
    );

`define MODULE_END endmodule

// A register stage
`define STAGE(name, width) \
    `MODULE_BEGIN(name, width) \
        `FF(q_o, d_i, '0) \
    `MODULE_END

`MODULE_BEGIN(module_macros, 8)
    logic [7:0] stage;
    stage8 u_stage0 (`CLK_RST_CON, .d_i(d_i), .q_o(stage));
    stage8 u_stage1 (`CLK_RST_CON, .d_i(stage), .q_o(q_o));
`MODULE_END

`STAGE(stage8, 8)
`STAGE(stage16, 16)
