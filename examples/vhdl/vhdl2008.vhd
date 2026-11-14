library ieee;
context ieee.ieee_std_context;

/* Block comments
   are part of VHDL-2008 */
entity vhdl2008 is
  generic (
    type data_t; -- Generic types are skipped
    MODE : natural := 0 /* Mode of operation */
  );
  port (
    clk  : in  std_logic;
    sel  : in  std_logic_vector(1 downto 0);
    din  : in  data_t;
    dout : out data_t
  );
end entity;

architecture rtl of vhdl2008 is
  signal a, b : data_t;
begin

  -- if generate with alternatives
  g_mode : if g_fast : MODE = 0 generate
    u_fast : entity work.fast
      port map (clk => clk, din => din, dout => a);
  elsif g_small : MODE = 1 generate
    signal tmp : data_t;
  begin
    u_small : entity work.small
      port map (clk => clk, din => din, dout => tmp);
    a <= tmp;
  end g_small;
  else generate
    a <= din;
  end generate g_mode;

  -- case generate
  g_sel : case MODE generate
    when 0 | 1 =>
      u_reg : entity work.reg
        generic map (data_t => data_t)
        port map (clk => clk, din => a, dout => b);
    when others =>
      b <= a;
  end generate g_sel;

  -- process sensitive to all signals
  process (all) is
  begin
    case sel is
      when "00"   => dout <= a;
      when others => dout <= b;
    end case;
  end process;

end architecture;
