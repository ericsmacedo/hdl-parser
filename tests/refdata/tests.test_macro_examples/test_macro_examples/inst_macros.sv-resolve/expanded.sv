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
    input  logic clk_i,  /* Clock */ 
    input  logic rst_ni  /* Reset, low active */,
    input  logic [7:0] data_i [3],
    output logic [7:0] data_o [3],
    input  logic       irq_i,
    output logic       irq_o
);
    logic cfg_psel, cfg_penable, cfg_pwrite, cfg_pready;
    logic [11:0] cfg_paddr;
    logic [31:0] cfg_pwdata, cfg_prdata;

    fifo #(.DEPTH(DEPTH)) u_fifo0 ( 
        .clk_i(clk_i), .rst_ni(rst_ni), 
        .data_i(data_i[0]), /* Input */ 
        .data_o(data_o[0])  /* Output */ 
    ); 
    monitor u_mon0 (.clk_i(clk_i), .rst_ni(rst_ni), .data_i(data_o[0]));
    fifo #(.DEPTH(DEPTH)) u_fifo1 ( 
        .clk_i(clk_i), .rst_ni(rst_ni), 
        .data_i(data_i[1]), /* Input */ 
        .data_o(data_o[1])  /* Output */ 
    ); 
    monitor u_mon1 (.clk_i(clk_i), .rst_ni(rst_ni), .data_i(data_o[1]));
    fifo #(.DEPTH(DEPTH)) u_fifo2 ( 
        .clk_i(clk_i), .rst_ni(rst_ni), 
        .data_i(data_i[2]), /* Input */ 
        .data_o(data_o[2])  /* Output */ 
    ); 
    monitor u_mon2 (.clk_i(clk_i), .rst_ni(rst_ni), .data_i(data_o[2]));

    sync #(.STAGES(2)) u_sync_irq (.clk_i(clk_i), .rst_ni(rst_ni), .d_i(irq_i), .q_o(irq_o));

    regs u_regs (
        .clk_i(clk_i), .rst_ni(rst_ni),
        .cfg_psel_i   (cfg_psel), 
    .cfg_penable_i(cfg_penable), 
    .cfg_pwrite_i (cfg_pwrite), 
    .cfg_paddr_i  (cfg_paddr), 
    .cfg_pwdata_i (cfg_pwdata), 
    .cfg_prdata_o (cfg_prdata), 
    .cfg_pready_o (cfg_pready)
    );

    // unknown macros are kept as they are
    `UNKNOWN_INST(u_unknown)
    other u_other (.clk_i(clk_i), .rst_ni(rst_ni), `UNKNOWN_CON(x), .y(`UNKNOWN_VALUE));
endmodule
