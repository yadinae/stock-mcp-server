/**
 * 游资席位速查表 — 22位知名游资席位数据库
 *
 * Based on UZI-Skill lib/seat_db.py, adapted for Workers Gateway.
 * Each seat entry maps an 营业部 name pattern → 游资 identity.
 */

export interface SeatEntry {
  id: string;
  name: string;
  realName?: string;
  tier: 'legend' | 'new_gen' | 'regional' | 'new_2025';
  style: string;
  premium: string;        // 'positive' | 'negative' | 'neutral' | 'neutral_positive'
  seats: string[];        // 营业部名称关键字（prefix match）
  fitRules: Record<string, any>;
}

export const SEATS: SeatEntry[] = [
  // ═══ 殿堂级 ═══
  {
    id: 'zhang_mz',
    name: '章盟主',
    realName: '章建平',
    tier: 'legend',
    style: '大资金趋势波段，格局锁仓',
    premium: 'neutral',
    seats: [
      '国泰君安证券股份有限公司上海江苏路证券营业部',
      '国泰君安证券股份有限公司宁波彩虹北路证券营业部',
      '中信证券股份有限公司杭州延安路证券营业部',
    ],
    fitRules: { minMcap: 200, trend: 'up' },
  },
  {
    id: 'sun_ge',
    name: '孙哥',
    realName: '孙煜',
    tier: 'legend',
    style: '板块引导，波段锁仓',
    premium: 'neutral_positive',
    seats: [
      '中信证券股份有限公司上海溧阳路证券营业部',
      '中信证券股份有限公司上海古北路证券营业部',
      '中信证券股份有限公司上海分公司',
    ],
    fitRules: { minMcap: 100, isSectorLeader: true },
  },
  {
    id: 'zhao_lg',
    name: '赵老哥',
    realName: '赵强',
    tier: 'legend',
    style: '打板，二板定龙头',
    premium: 'positive',
    seats: [
      '浙商证券股份有限公司绍兴解放北路证券营业部',
      '中国银河证券股份有限公司绍兴证券营业部',
      '中国银河证券股份有限公司北京阜成路证券营业部',
    ],
    fitRules: { isFirstOrSecondBoard: true, isSectorLeader: true },
  },
  {
    id: 'fs_wyj',
    name: '佛山无影脚',
    realName: '廖国沛',
    tier: 'legend',
    style: '一日游，翘板，砸盘王',
    premium: 'negative',
    seats: [
      '光大证券股份有限公司佛山绿景路证券营业部',
      '光大证券股份有限公司佛山季华六路证券营业部',
      '湘财证券股份有限公司佛山祖庙路证券营业部',
    ],
    fitRules: { maxMcap: 80 },
  },
  {
    id: 'yangjia',
    name: '炒股养家',
    tier: 'legend',
    style: '情绪揣摩，通道排板',
    premium: 'next_day_70',
    seats: [
      '华鑫证券有限责任公司上海红宝石路证券营业部',
      '华鑫证券有限责任公司上海宛平南路证券营业部',
    ],
    fitRules: { sentimentCycle: true },
  },

  // ═══ 新生代 ═══
  {
    id: 'chen_xq',
    name: '陈小群',
    realName: '陈宴群',
    tier: 'new_gen',
    style: '龙头接力、一线天、反核按钮',
    premium: 'next_day_57',
    seats: ['中国银河证券股份有限公司大连黄河路证券营业部'],
    fitRules: { isSectorLeader: true, isHotTheme: true },
  },
  {
    id: 'hu_jl',
    name: '呼家楼',
    tier: 'new_gen',
    style: '多席位协同、板块平铺扫货',
    premium: 'neutral',
    seats: [
      '中信证券股份有限公司上海凯滨路证券营业部',
      '中信证券股份有限公司北京总部',
      '中信建投证券股份有限公司北京朝外大街证券营业部',
    ],
    fitRules: { isHottestInSector: true },
  },
  {
    id: 'fang_xx',
    name: '方新侠',
    tier: 'new_gen',
    style: '大成交趋势票、格局锁仓',
    premium: 'neutral',
    seats: [
      '兴业证券股份有限公司陕西分公司',
      '中信证券股份有限公司西安朱雀大街证券营业部',
    ],
    fitRules: { minTurnover: 10 },
  },
  {
    id: 'zuoshou',
    name: '作手新一',
    realName: '严冬',
    tier: 'new_gen',
    style: '龙头战法，连板+趋势兼做',
    premium: 'neutral',
    seats: ['国泰君安证券股份有限公司南京太平南路证券营业部'],
    fitRules: { isSectorLeader: true },
  },
  {
    id: 'xiao_ey',
    name: '小鳄鱼',
    tier: 'new_gen',
    style: '基本面辅助选股',
    premium: 'neutral',
    seats: [
      '南京证券股份有限公司南京大钟亭证券营业部',
      '中金财富证券有限公司南京龙蟠中路证券营业部',
    ],
    fitRules: { minFundamentalScore: 70 },
  },
  {
    id: 'jiao_yy',
    name: '交易猿',
    tier: 'new_gen',
    style: '大容量票锁仓、龙头加速',
    premium: 'neutral',
    seats: [
      '华泰证券股份有限公司天津东丽开发区二纬路证券营业部',
      '招商证券股份有限公司福州六一中路证券营业部',
    ],
    fitRules: { minMcap: 150, isSectorLeader: true },
  },
  {
    id: 'mao_lb',
    name: '毛老板',
    tier: 'new_gen',
    style: 'AI主线大资金重仓',
    premium: 'neutral',
    seats: [
      '国泰君安证券股份有限公司北京光华路证券营业部',
      '方正证券股份有限公司乐山龙游路证券营业部',
      '广发证券股份有限公司上海东方路证券营业部',
    ],
    fitRules: { isAiTheme: true, minMcap: 100 },
  },
  {
    id: 'xiao_xian',
    name: '消闲派',
    tier: 'new_gen',
    style: '满仓满融极致进攻',
    premium: 'neutral',
    seats: ['华泰证券股份有限公司浙江分公司'],
    fitRules: { isAccelerating: true },
  },

  // ═══ 区域帮派 ═══
  {
    id: 'lasa',
    name: '拉萨天团',
    tier: 'regional',
    style: '群狼一日游，反向指标',
    premium: 'negative',
    seats: ['东方财富证券股份有限公司拉萨'],
    fitRules: { shortTermOnly: true },
  },
  {
    id: 'chengdu',
    name: '成都帮',
    tier: 'regional',
    style: '底部黑马点火一日游',
    premium: 'neutral',
    seats: ['华泰证券股份有限公司成都南一环路第二证券营业部'],
    fitRules: { isOversold: true },
  },
  {
    id: 'sunang',
    name: '苏南帮',
    tier: 'regional',
    style: '多席位联动低价小盘',
    premium: 'neutral',
    seats: [
      '华泰证券股份有限公司无锡',
      '华泰证券股份有限公司镇江',
      '华泰证券股份有限公司南京',
    ],
    fitRules: { maxMcap: 50 },
  },
  {
    id: 'ningbo',
    name: '宁波桑田路',
    tier: 'regional',
    style: '连板接力',
    premium: 'neutral',
    seats: ['国盛证券有限责任公司宁波桑田路证券营业部'],
    fitRules: { isContinuousLimitUp: true },
  },

  // ═══ 2025 新晋 ═══
  {
    id: 'liuyizhong',
    name: '六一中路',
    tier: 'new_2025',
    style: '题材打板接力',
    premium: 'neutral',
    seats: ['招商证券股份有限公司福州六一中路证券营业部'],
    fitRules: { isHotTheme: true, isSectorLeader: true },
  },
  {
    id: 'liushahe',
    name: '流沙河',
    tier: 'new_2025',
    style: '低吸/接力新晋',
    premium: 'neutral',
    seats: [
      '招商证券股份有限公司北京车公庄西路证券营业部',
      '华泰证券股份有限公司上海武定路证券营业部',
    ],
    fitRules: { isHotTheme: true },
  },
  {
    id: 'gubei',
    name: '古北路',
    tier: 'new_2025',
    style: '2025 重新活跃顶级短线',
    premium: 'neutral',
    seats: ['中信证券股份有限公司上海古北路证券营业部'],
    fitRules: { isSectorLeader: true },
  },
  {
    id: 'ghzw',
    name: '股海贼王',
    tier: 'new_2025',
    style: '弱转强、首板、反核，专注A股短线',
    premium: 'neutral',
    seats: [
      '国泰君安证券股份有限公司沈阳十一纬路证券营业部',
      '华泰证券股份有限公司上海杨浦区国宾路证券营业部',
    ],
    fitRules: { isWeakToStrong: true, isLimitUp: true },
  },
];

/**
 * Match seat name against known 游资.
 * Returns matched entries with confidence level.
 */
export function matchSeat(seatName: string): { entry: SeatEntry; confidence: string } | null {
  for (const entry of SEATS) {
    for (const pattern of entry.seats) {
      if (seatName.includes(pattern)) {
        return { entry, confidence: 'high' };
      }
    }
  }
  return null;
}

/**
 * Check if a seat name looks institutional.
 */
export function isInstitutional(seatName: string): boolean {
  return seatName.includes('机构专用') ||
    (seatName.includes('机构') && !seatName.includes('证券'));
}
