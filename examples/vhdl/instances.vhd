library ieee;
use ieee.std_logic_1164.all;

entity instances is
  generic (
    STAGES : positive := 4
  );
  port (
    clk  : in  std_logic;
    rst  : in  std_logic;
    din  : in  std_logic_vector(7 downto 0);
    dout : out std_logic_vector(7 downto 0)
  );
end entity instances;

architecture rtl of instances is

  -- Component declarations are not instances
  component stage is
    generic (
      WIDTH : positive := 8
    );
    port (
      clk  : in  std_logic;
      din  : in  std_logic_vector(WIDTH - 1 downto 0);
      dout : out std_logic_vector(WIDTH - 1 downto 0)
    );
  end component stage;

  type data_t is array (0 to STAGES) of std_logic_vector(7 downto 0);

  type status_t is record
    valid : std_logic;
    error : std_logic;
  end record status_t;

  -- Subprograms are skipped
  function parity (value : std_logic_vector) return std_logic is
    variable result : std_logic := '0';
  begin
    for idx in value'range loop
      if value(idx) = '1' then
        result := not result;
      end if;
    end loop;
    return result;
  end function parity;

  signal data   : data_t;
  signal status : status_t;
  signal par    : std_logic;

begin

  data(0) <= din;

  -- Component instance
  u_first : stage
    generic map (
      WIDTH => 8
    )
    port map (
      clk  => clk, -- Clock
      din  => data(0), -- Input of the first stage
      dout => data(1)
    );

  -- Component instance with keyword
  u_second : component stage
    port map (clk, data(1), data(2)); -- Connections by order

  -- Direct entity instance
  u_third : entity work.stage(rtl)
    generic map (WIDTH => 8)
    port map (
      clk  => clk,
      din  => data(2),
      dout => open -- Unconnected
    );

  -- Instances within generate statements
  g_stages : for idx in 3 to STAGES - 1 generate
    u_stage : entity work.stage
      port map (
        clk  => clk,
        din  => data(idx),
        dout => data(idx + 1)
      );
  end generate g_stages;

  g_parity : if STAGES > 2 generate
    u_parity : entity work.parity_gen
      port map (
        din    => data(STAGES),
        parity => par
      );
  end generate g_parity;

  -- Instance within a block
  b_sync : block is
    signal synced : std_logic;
  begin
    u_sync : entity work.sync
      port map (
        clk  => clk,
        din  => rst,
        dout => synced
      );
  end block b_sync;

  -- Processes are skipped
  p_out : process (clk) is
  begin
    if rising_edge(clk) then
      if rst = '1' then
        dout <= (others => '0');
      else
        dout <= data(STAGES);
      end if;
    end if;
  end process p_out;

  -- Concurrent statements are no instances
  status.valid <= '1' when rst = '0' else '0';
  check : assert STAGES < 16 report "Too many stages" severity failure;

end architecture rtl;
