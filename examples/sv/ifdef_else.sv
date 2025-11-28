module ifdef_else #(
`ifdef MOD_PARAM
parameter PARAM = `MOD_PARAM,
`else
parameter PARAM = 4,
`endif
`ifdef MOD_PARAM2
parameter PARAM2 = `MOD_PARAM2
`else
parameter PARAM2 = 4
`endif
)

(
    input [PARAM-1:0] inp,
    output [PARAM-1:0] outp,
)

endmodule
