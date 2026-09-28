/** Only the ECharts parts the app uses (keeps the bundle small). */
import { BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, BarChart, GridComponent, TooltipComponent, MarkAreaComponent, MarkLineComponent, CanvasRenderer])
