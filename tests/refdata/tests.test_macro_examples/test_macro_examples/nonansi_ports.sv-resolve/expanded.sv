// Non-ANSI module header: the ports are declared by macros in the module body.
`include "common.svh"

`define IN(name, width=1) input wire [width-1:0] name;
`define OUT(name, width=1) output reg [width-1:0] name;
`define HANDSHAKE(prefix) \
    `IN(prefix``_req) \
    `OUT(prefix``_ack)

module nonansi_ports (clk, rst_n, cmd, cmd_req, cmd_ack, rsp, rsp_req, rsp_ack);
    parameter WIDTH = 8;
    input wire [1-1:0] clk;
    input wire [1-1:0] rst_n;
    input wire [WIDTH-1:0] cmd;
    input wire [1-1:0] cmd_req; 
    output reg [1-1:0] cmd_ack;
    output reg [2*WIDTH-1:0] rsp;
    input wire [1-1:0] rsp_req; 
    output reg [1-1:0] rsp_ack;

    always @(posedge clk) begin
        rsp <= {cmd, cmd};
    end
endmodule
