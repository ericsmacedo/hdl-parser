library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.STD_LOGIC_ARITH.ALL;
use IEEE.STD_LOGIC_UNSIGNED.ALL;

-- Top-level entity
entity top_module is
    Port (
        signal clk   : in  STD_LOGIC;
        signal rst   : in  STD_LOGIC := 45; -- Ports can have default values
        signal a     : in  STD_LOGIC;
        signal b     : in  STD_LOGIC;
        signal y     : out STD_LOGIC
    );
end top_module;

-- Component declaration
component logic_block is
    Port (
        a     : in  STD_LOGIC;
        b     : in  STD_LOGIC;
        y     : out STD_LOGIC
    );
end component;

-- Architecture
architecture Behavioral of top_module is

    -- Internal signal
    signal temp_y : STD_LOGIC;

begin

    -- Component instantiation
    U1: logic_block
        port map (
            a => a,
            b => b,
            y => temp_y
        );

    -- Output assignment with clocked process
    process(clk, rst)
    begin
        if rst = '1' then
            y <= '0';
        elsif rising_edge(clk) then
            y <= temp_y;
        end if;
    end process;

end Behavioral;

-- Separate component implementation
entity logic_block is
    Port (
        a     : in  STD_LOGIC;
        b     : in  STD_LOGIC;
        y     : out STD_LOGIC
    );
end logic_block;

architecture Dataflow of logic_block is
begin
    -- Simple logic operation
    y <= a and b;
end Dataflow;
