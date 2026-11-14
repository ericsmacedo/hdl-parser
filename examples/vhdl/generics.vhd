library ieee;
use ieee.std_logic_1164.all;

-- Generics with and without default value
entity generics is
  generic (
    -- Generic without default value
    WIDTH      : positive;
    DEPTH      : natural range 1 to 1024 := 16; -- Constrained integer
    RESET_VAL  : std_logic_vector(7 downto 0) := (others => '0'); -- Vector with aggregate
    NAME       : string := "fifo"; -- String
    SIM, DEBUG : boolean := false; -- Two generics in one declaration
    constant TIMEOUT : time := 10 ns -- Explicit object class
  );
  port (
    clk  : in  std_logic;
    din  : in  std_logic_vector(WIDTH - 1 downto 0);
    dout : out std_logic_vector(WIDTH - 1 downto 0)
  );
end entity generics;
