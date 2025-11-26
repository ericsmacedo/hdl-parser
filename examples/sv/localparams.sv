module localparams (A, B, X);
  parameter integer DATA_WIDTH = 8;
  localparam integer MY_WIDTH = DATA_WIDTH + 1;
  input  unsigned [DATA_WIDTH-1:0] A;
  input  unsigned [DATA_WIDTH-1:0] B;
  output unsigned [MY_WIDTH-1:0]   X;
)

endmodule
