// Non-ANSI module header: the ports are declared by macros in the module body.
`include "common.svh"

`define IN(name, width=1) input wire [width-1:0] name;
`define OUT(name, width=1) output reg [width-1:0] name;
`define HANDSHAKE(prefix) \
    `IN(prefix``_req) \
    `OUT(prefix``_ack)

module nonansi_ports (clk, rst_n, cmd, cmd_req, cmd_ack, rsp, rsp_req, rsp_ack);
    parameter WIDTH = 8;
    `IN(clk)
    `IN(rst_n)
    `IN(cmd, WIDTH)
    `HANDSHAKE(cmd)
    `OUT(rsp, 2*WIDTH)
    `HANDSHAKE(rsp)

    always @(posedge clk) begin
        rsp <= {cmd, cmd};
    end
endmodule
