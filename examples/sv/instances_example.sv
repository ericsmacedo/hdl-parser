module top1(
   input        clk,
   input        rst_n,
   input        enable,
   input  [9:0] data_rx_1,
   input  [9:0] data_rx_2,
   output [9:0] data_tx_2
);

subcomponent subcomponent_instance_name (
  .clk(clk), .rst_n(rst_n), .data_rx(data_rx_1), .data_tx(data_tx) ); 

endmodule

module top2(
   input        clk,
   input        rst_n,
   input        enable,
   input  [9:0] data_rx_1,
   input  [9:0] data_rx_2,
   output [9:0] data_tx_2
);


subcomponent subcomponent_instance_name (
  .clk      ( clk       ), // input
`ifdef BAR
  .rst_n    ( rst_n_bar     ), // input
`else
  .rst_n    ( rst_n_else     ), // input
`endif
  .data_rx  ( data_rx_1 ), // input  [9:0]
  .data_tx  ( data_tx   )  // output [9:0]
);

endmodule


module top3(
   input        clk,
   input        rst_n,
   input        enable,
   input  [9:0] data_rx_1,
   input  [9:0] data_rx_2,
   output [9:0] data_tx_2
);

subcomponent subcomponent_instance_name (
  .clk,                    // input **Auto connect**
  .rst_n,                  // input **Auto connect**
  .data_rx  ( data_rx_1 ), // input  [9:0]
  .data_tx  ( data_tx   )  // output [9:0]
);

subcomponent unconnected_instance ();

endmodule

module top4(
   input        clk,
   input        rst_n,
   input        enable,
   input  [9:0] data_rx_1,
   input  [9:0] data_rx_2,
   output [9:0] data_tx_2
);

subcomponent subcomponent_instance_name (
  .*,                      // **Auto connect**
  .data_rx  ( data_rx_1 ), // input  [9:0]
  .data_tx  ( data_tx   )  // output [9:0]
);

endmodule

module top0(
   input        clk,
   input        rst_n,
   input        enable,
   input  [9:0] data_rx_1,
   input  [9:0] data_rx_2,
   output [9:0] data_tx_2
);

`ifdef SYNTHESIS
subcomponent subcomponent_instance_name (
  clk, rst_n, data_rx_1, data_tx ); 
`endif

endmodule
