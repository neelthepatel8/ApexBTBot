from construct import (
    Struct,
    Bytes,
    Array,
    Int8ul,
    Int16ul,
    Int32sl,
    Int64ul,
    Padding,
    BitsInteger,
    BitsSwapped,
    BitStruct,
    Const,
    Flag,
    BytesInteger,
    Adapter,
)


class UInt128Adapter(Adapter):
    def _decode(self, obj, context, path):
        return (obj.high << 64) | obj.low

    def _encode(self, obj, context, path):
        high = (obj >> 64) & ((1 << 64) - 1)
        low = obj & ((1 << 64) - 1)
        return dict(high=high, low=low)


UInt128ul = UInt128Adapter(Struct("low" / Int64ul, "high" / Int64ul))

POSITION_REWARD_INFO = Struct(
    "reward_amount" / UInt128ul, "reward_growth_inside" / UInt128ul
)


CPMM_POOL_STATE_LAYOUT = Struct(
    Padding(8),
    "amm_config" / Bytes(32),
    "pool_creator" / Bytes(32),
    "token_0_vault" / Bytes(32),
    "token_1_vault" / Bytes(32),
    "lp_mint" / Bytes(32),
    "token_0_mint" / Bytes(32),
    "token_1_mint" / Bytes(32),
    "token_0_program" / Bytes(32),
    "token_1_program" / Bytes(32),
    "observation_key" / Bytes(32),
    "auth_bump" / Int8ul,
    "status" / Int8ul,
    "lp_mint_decimals" / Int8ul,
    "mint_0_decimals" / Int8ul,
    "mint_1_decimals" / Int8ul,
    "lp_supply" / Int64ul,
    "protocol_fees_token_0" / Int64ul,
    "protocol_fees_token_1" / Int64ul,
    "fund_fees_token_0" / Int64ul,
    "fund_fees_token_1" / Int64ul,
    "open_time" / Int64ul,
    "padding" / Array(32, Int64ul),
)


CLMM_POOL_STATE_LAYOUT = Struct(
    Padding(8),
    "bump" / Int8ul,
    "amm_config" / Bytes(32),
    "owner" / Bytes(32),
    "token_mint_0" / Bytes(32),
    "token_mint_1" / Bytes(32),
    "token_vault_0" / Bytes(32),
    "token_vault_1" / Bytes(32),
    "observation_key" / Bytes(32),
    "mint_decimals_0" / Int8ul,
    "mint_decimals_1" / Int8ul,
    "tick_spacing" / Int16ul,
    "liquidity" / UInt128ul,
    "sqrt_price_x64" / UInt128ul,
    "tick_current" / Int32sl,
    "observation_index" / Int16ul,
    "observation_update_duration" / Int16ul,
    "fee_growth_global_0_x64" / UInt128ul,
    "fee_growth_global_1_x64" / UInt128ul,
    "protocol_fees_token_0" / Int64ul,
    "protocol_fees_token_1" / Int64ul,
    "swap_in_amount_token_0" / UInt128ul,
    "swap_out_amount_token_1" / UInt128ul,
    "swap_in_amount_token_1" / UInt128ul,
    "swap_out_amount_token_0" / UInt128ul,
    "status" / Int8ul,
    "padding" / Array(7, Int8ul),
    "reward_infos" / Array(3, POSITION_REWARD_INFO),
    "tick_array_bitmap" / Array(16, Int64ul),
    "total_fees_token_0" / Int64ul,
    "total_fees_claimed_token_0" / Int64ul,
    "total_fees_token_1" / Int64ul,
    "total_fees_claimed_token_1" / Int64ul,
    "fund_fees_token_0" / Int64ul,
    "fund_fees_token_1" / Int64ul,
    "padding1" / Array(26, Int64ul),
    "padding2" / Array(32, Int64ul),
)

LIQUIDITY_STATE_LAYOUT_V4 = Struct(
    "status" / Int64ul,
    "nonce" / Int64ul,
    "orderNum" / Int64ul,
    "depth" / Int64ul,
    "coinDecimals" / Int64ul,
    "pcDecimals" / Int64ul,
    "state" / Int64ul,
    "resetFlag" / Int64ul,
    "minSize" / Int64ul,
    "volMaxCutRatio" / Int64ul,
    "amountWaveRatio" / Int64ul,
    "coinLotSize" / Int64ul,
    "pcLotSize" / Int64ul,
    "minPriceMultiplier" / Int64ul,
    "maxPriceMultiplier" / Int64ul,
    "systemDecimalsValue" / Int64ul,
    "minSeparateNumerator" / Int64ul,
    "minSeparateDenominator" / Int64ul,
    "tradeFeeNumerator" / Int64ul,
    "tradeFeeDenominator" / Int64ul,
    "pnlNumerator" / Int64ul,
    "pnlDenominator" / Int64ul,
    "swapFeeNumerator" / Int64ul,
    "swapFeeDenominator" / Int64ul,
    "needTakePnlCoin" / Int64ul,
    "needTakePnlPc" / Int64ul,
    "totalPnlPc" / Int64ul,
    "totalPnlCoin" / Int64ul,
    "poolOpenTime" / Int64ul,
    "punishPcAmount" / Int64ul,
    "punishCoinAmount" / Int64ul,
    "orderbookToInitTime" / Int64ul,
    "swapCoinInAmount" / BytesInteger(16, signed=False, swapped=True),
    "swapPcOutAmount" / BytesInteger(16, signed=False, swapped=True),
    "swapCoin2PcFee" / Int64ul,
    "swapPcInAmount" / BytesInteger(16, signed=False, swapped=True),
    "swapCoinOutAmount" / BytesInteger(16, signed=False, swapped=True),
    "swapPc2CoinFee" / Int64ul,
    "poolCoinTokenAccount" / Bytes(32),
    "poolPcTokenAccount" / Bytes(32),
    "coinMintAddress" / Bytes(32),
    "pcMintAddress" / Bytes(32),
    "lpMintAddress" / Bytes(32),
    "ammOpenOrders" / Bytes(32),
    "serumMarket" / Bytes(32),
    "serumProgramId" / Bytes(32),
    "ammTargetOrders" / Bytes(32),
    "poolWithdrawQueue" / Bytes(32),
    "poolTempLpTokenAccount" / Bytes(32),
    "ammOwner" / Bytes(32),
    "pnlOwner" / Bytes(32),
)

ACCOUNT_FLAGS_LAYOUT = BitsSwapped(
    BitStruct(
        "initialized" / Flag,
        "market" / Flag,
        "open_orders" / Flag,
        "request_queue" / Flag,
        "event_queue" / Flag,
        "bids" / Flag,
        "asks" / Flag,
        Const(0, BitsInteger(57)),
    )
)

MARKET_STATE_LAYOUT_V3 = Struct(
    Padding(5),
    "account_flags" / ACCOUNT_FLAGS_LAYOUT,
    "own_address" / Bytes(32),
    "vault_signer_nonce" / Int64ul,
    "base_mint" / Bytes(32),
    "quote_mint" / Bytes(32),
    "base_vault" / Bytes(32),
    "base_deposits_total" / Int64ul,
    "base_fees_accrued" / Int64ul,
    "quote_vault" / Bytes(32),
    "quote_deposits_total" / Int64ul,
    "quote_fees_accrued" / Int64ul,
    "quote_dust_threshold" / Int64ul,
    "request_queue" / Bytes(32),
    "event_queue" / Bytes(32),
    "bids" / Bytes(32),
    "asks" / Bytes(32),
    "base_lot_size" / Int64ul,
    "quote_lot_size" / Int64ul,
    "fee_rate_bps" / Int64ul,
    "referrer_rebate_accrued" / Int64ul,
    Padding(7),
)
