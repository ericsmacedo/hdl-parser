// Instances and connections created by macros.
`include "bus.svh"

// One channel: a fifo and its monitor
`define CHANNEL(idx) \
    fifo #(.DEPTH(DEPTH)) u_fifo``idx ( \
        `CLK_RST_CON, \
        .data_i(data_i[idx]), /* Input */ \
        .data_o(data_o[idx])  /* Output */ \
    ); \
    monitor u_mon``idx (`CLK_RST_CON, .data_i(data_o[idx]));

`define SYNC(name, src, dst) sync #(.STAGES(2)) u_sync_``name (`CLK_RST_CON, .d_i(src), .q_o(dst));

module inst_macros #(
    parameter int DEPTH = 4
) (
    `CLK_RST_PORTS,
    input  logic [7:0] data_i [3],
    output logic [7:0] data_o [3],
    input  logic       irq_i,
    output logic       irq_o
);
    logic cfg_psel, cfg_penable, cfg_pwrite, cfg_pready;
    logic [11:0] cfg_paddr;
    logic [31:0] cfg_pwdata, cfg_prdata;

    `CHANNEL(0)
    `CHANNEL(1)
    `CHANNEL(2)

    `SYNC(irq, irq_i, irq_o)

    regs u_regs (
        `CLK_RST_CON,
        `APB_CON(cfg)
    );

    // unknown macros are kept as they are
    `UNKNOWN_INST(u_unknown)
    other u_other (`CLK_RST_CON, `UNKNOWN_CON(x), .y(`UNKNOWN_VALUE));
endmodule
