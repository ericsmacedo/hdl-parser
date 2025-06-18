library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity uart_tx is
  generic (
    CLK_FREQ    : integer := 100_000_000; -- Clock frequency in Hz
                                          -- (default: 100 MHz)
    
    BAUD_RATE   : integer := (115_200); -- Baud rate (default: 115200)
    
    -- Data bits (default: 8-bit)
    DATA_WIDTH  : positive := (8+5);
    
    -- Parity mode: 0 = none, 1 = odd, 2 = even
    --PARITY_MODE : natural range 0 to 2 := 0
  );
  port (
    -- System clock and active-high reset
    clk, clk_2  : in  std_logic; -- System clock
    reset       : in  std_logic; -- active-high reset
    
    -- Data interface
    data_in     : in  std_logic_vector(DATA_WIDTH-1 downto 0);
    data_valid  : in  std_logic;
    ready       : out std_logic;
    
    -- Serial output
    txd         : out std_logic;
    
    -- Status signals
    parity_error: out std_logic
  );
end entity uart_tx;
