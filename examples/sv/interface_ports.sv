// Interface and modport ports mixed with regular ports
module interface_ports (
  input  logic      clk,
  axi_if.master     axi_m,  // master modport
  axi_if.slave      axi_s,  // slave modport
  apb_if            apb,    // generic interface
  output logic      irq
);
endmodule
