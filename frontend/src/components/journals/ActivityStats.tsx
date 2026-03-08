import {
  Activity,
  Clock,
  Flame,
  Heart,
  Mountain,
  Ruler,
  Cloud,
  Compass,
} from 'lucide-react';
import type {
  AbseilingData,
  CanyoningData,
  ClimbingData,
  CrossCountrySkiingData,
  FitnessData,
  BushwalkingData,
  JoggingData,
  KayakingData,
  OutdoorActivityData,
} from '@/types/journals';
import type { Route } from '@/types/routes';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';

interface ActivityStatsProps {
  readonly data?: FitnessData;
  readonly outdoorData?: OutdoorActivityData;
  readonly joggingData?: JoggingData;
  readonly bushwalkingData?: BushwalkingData;
  readonly abseilingData?: AbseilingData;
  readonly canyoningData?: CanyoningData;
  readonly climbingData?: ClimbingData;
  readonly kayakingData?: KayakingData;
  readonly crossCountrySkiingData?: CrossCountrySkiingData;
  readonly routeDisplay?: Route;
  readonly className?: string;
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function formatDistance(meters: number): string {
  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(2)} km`;
  }
  return `${meters} m`;
}

export function formatPace(
  durationSecs: number,
  distanceMeters: number
): string {
  if (distanceMeters === 0) return '-';
  const km = distanceMeters / 1000;
  const secsPerKm = durationSecs / km;
  const m = Math.floor(secsPerKm / 60);
  const s = Math.floor(secsPerKm % 60);
  return `${m}:${s.toString().padStart(2, '0')} /km`;
}

/**
 * Format an already-computed seconds-per-km pace value into "mm:ss /km".
 * Use this instead of formatPace() when the pace is already known.
 */
export function formatSecondsPerKm(secsPerKm: number): string {
  const m = Math.floor(secsPerKm / 60);
  const s = Math.floor(secsPerKm % 60);
  return `${m}:${s.toString().padStart(2, '0')} /km`;
}

interface StatItemProps {
  readonly icon: React.ReactNode;
  readonly label: string;
  readonly value: React.ReactNode;
  readonly testId?: string;
}

function StatItem({ icon, label, value, testId }: StatItemProps) {
  return (
    <div className='flex items-center gap-3'>
      <div className='bg-primary/10 text-primary rounded-full p-2'>{icon}</div>
      <div>
        <p className='text-muted-foreground text-xs font-medium'>{label}</p>
        <p className='text-sm font-semibold' data-testid={testId}>
          {value}
        </p>
      </div>
    </div>
  );
}

interface StatsSectionProps {
  readonly title: string;
  readonly description: string;
  readonly items: readonly React.ReactNode[];
  readonly testId: string;
}

function StatsSection({
  title,
  description,
  items,
  testId,
}: StatsSectionProps) {
  return (
    <section className='space-y-3' data-testid={testId}>
      <div className='space-y-1'>
        <h3 className='text-sm font-semibold'>{title}</h3>
        <p className='text-muted-foreground text-xs'>{description}</p>
      </div>
      <div className='grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3'>
        {items}
      </div>
    </section>
  );
}

export function ActivityStats({
  data,
  outdoorData,
  joggingData,
  bushwalkingData,
  abseilingData,
  canyoningData,
  climbingData,
  kayakingData,
  crossCountrySkiingData,
  routeDisplay,
  className,
}: ActivityStatsProps) {
  const fitness = data ?? {};
  const distance = fitness.distance;
  const duration = fitness.duration;
  const elevationGain = fitness.elevation_gain;
  const averageHeartRate = fitness.heart_rate_avg;
  const calories = fitness.calories;
  const weatherConditions = outdoorData?.weather_conditions;
  const trackGrading = bushwalkingData?.track_grading;
  const numberOfAbseils = abseilingData?.number_of_abseils;
  const totalLength = abseilingData?.total_length;
  const frenchGrade = canyoningData?.french_grade;
  const waterGaugeName = canyoningData?.water_guage_name;
  const waterGaugeLevel = canyoningData?.water_guage_level;
  const climbingType = climbingData?.climbing_type;
  const climbingGrade = climbingData?.grade;
  const climbingLength = climbingData?.length;
  const waterType = kayakingData?.water_type;
  const snowConditions = crossCountrySkiingData?.snow_conditions;
  const joggingPace = joggingData?.pace;

  const hasDistance = distance != null && distance > 0;
  const hasDuration = duration != null && duration > 0;
  const hasElevation = elevationGain != null && elevationGain > 0;
  const hasHr = averageHeartRate != null && averageHeartRate > 0;
  const hasCalories = calories != null && calories > 0;
  const hasWeather = weatherConditions != null && weatherConditions !== '';
  const hasGrading = trackGrading != null && trackGrading !== '';
  const hasAbseils = numberOfAbseils != null && numberOfAbseils > 0;
  const hasTotalLength = totalLength != null && totalLength > 0;
  const hasFrenchGrade = frenchGrade != null && frenchGrade !== '';
  const hasWaterGauge =
    (waterGaugeName != null && waterGaugeName !== '') ||
    waterGaugeLevel != null;
  const canyonFlags = [
    canyoningData?.is_vertical ? 'Vertical' : null,
    canyoningData?.is_night_canyon ? 'Night Canyon' : null,
    canyoningData?.is_white_water ? 'White Water' : null,
  ].filter((flag): flag is string => flag !== null);
  const hasCanyonFlags = canyonFlags.length > 0;
  const hasClimbingType = climbingType != null && climbingType !== '';
  const hasClimbingGrade = climbingGrade != null && climbingGrade > 0;
  const hasClimbingLength = climbingLength != null && climbingLength > 0;
  const hasWaterType = waterType != null && waterType !== '';
  const hasSnowConditions = snowConditions != null && snowConditions !== '';
  const hasJoggingPace = joggingPace != null && joggingPace > 0;
  const showCalculatedPace = hasDistance && hasDuration && !hasJoggingPace;

  const performanceItems: React.ReactNode[] = [];
  const contextItems: React.ReactNode[] = [];
  const technicalItems: React.ReactNode[] = [];

  if (distance != null && distance > 0) {
    performanceItems.push(
      <StatItem
        key='distance'
        icon={<Ruler className='h-4 w-4' />}
        label='Distance'
        value={formatDistance(distance)}
        testId='stat-distance'
      />
    );
  }

  if (duration != null && duration > 0) {
    performanceItems.push(
      <StatItem
        key='duration'
        icon={<Clock className='h-4 w-4' />}
        label='Duration'
        value={formatDuration(duration)}
        testId='stat-duration'
      />
    );
  }

  if (joggingPace != null && joggingPace > 0) {
    performanceItems.push(
      <StatItem
        key='pace-jogging'
        icon={<Activity className='h-4 w-4' />}
        label='Pace'
        value={formatSecondsPerKm(joggingPace)}
        testId='stat-pace-jogging'
      />
    );
  }

  if (showCalculatedPace) {
    performanceItems.push(
      <StatItem
        key='pace'
        icon={<Activity className='h-4 w-4' />}
        label='Pace'
        value={formatPace(duration as number, distance as number)}
        testId='stat-pace'
      />
    );
  }

  if (hasElevation) {
    performanceItems.push(
      <StatItem
        key='elevation'
        icon={<Mountain className='h-4 w-4' />}
        label='Elevation Gain'
        value={`${fitness.elevation_gain} m`}
        testId='stat-elevation'
      />
    );
  }

  if (hasHr) {
    performanceItems.push(
      <StatItem
        key='hr'
        icon={<Heart className='h-4 w-4' />}
        label='Avg HR'
        value={`${fitness.heart_rate_avg} bpm`}
        testId='stat-hr'
      />
    );
  }

  if (hasCalories) {
    performanceItems.push(
      <StatItem
        key='calories'
        icon={<Flame className='h-4 w-4' />}
        label='Calories'
        value={`${fitness.calories} kcal`}
        testId='stat-calories'
      />
    );
  }

  if (routeDisplay) {
    contextItems.push(
      <StatItem
        key='route'
        icon={<Mountain className='h-4 w-4' />}
        label='Route'
        value={routeDisplay.name}
        testId='stat-route'
      />
    );
  }

  if (hasWeather) {
    contextItems.push(
      <StatItem
        key='weather'
        icon={<Cloud className='h-4 w-4' />}
        label='Weather'
        value={weatherConditions}
        testId='stat-weather'
      />
    );
  }

  if (hasGrading) {
    contextItems.push(
      <StatItem
        key='grading'
        icon={<Compass className='h-4 w-4' />}
        label='Track Grade'
        value={trackGrading}
        testId='stat-grading'
      />
    );
  }

  if (hasWaterGauge) {
    contextItems.push(
      <StatItem
        key='water-gauge'
        icon={<Cloud className='h-4 w-4' />}
        label='Water Gauge'
        value={`${waterGaugeName ?? 'Gauge'}${
          waterGaugeLevel != null ? ` (${waterGaugeLevel})` : ''
        }`}
        testId='stat-water-gauge'
      />
    );
  }

  if (hasWaterType) {
    contextItems.push(
      <StatItem
        key='water-type'
        icon={<Cloud className='h-4 w-4' />}
        label='Water Type'
        value={waterType}
        testId='stat-water-type'
      />
    );
  }

  if (hasSnowConditions) {
    contextItems.push(
      <StatItem
        key='snow-conditions'
        icon={<Cloud className='h-4 w-4' />}
        label='Snow Conditions'
        value={snowConditions}
        testId='stat-snow-conditions'
      />
    );
  }

  if (hasAbseils) {
    technicalItems.push(
      <StatItem
        key='abseils'
        icon={<Activity className='h-4 w-4' />}
        label='Abseils'
        value={numberOfAbseils}
        testId='stat-abseils'
      />
    );
  }

  if (hasTotalLength) {
    technicalItems.push(
      <StatItem
        key='total-length'
        icon={<Ruler className='h-4 w-4' />}
        label='Total Length'
        value={`${totalLength} m`}
        testId='stat-total-length'
      />
    );
  }

  if (hasFrenchGrade) {
    technicalItems.push(
      <StatItem
        key='french-grade'
        icon={<Compass className='h-4 w-4' />}
        label='French Grade'
        value={frenchGrade}
        testId='stat-french-grade'
      />
    );
  }

  if (hasCanyonFlags) {
    technicalItems.push(
      <StatItem
        key='canyon-flags'
        icon={<Mountain className='h-4 w-4' />}
        label='Canyon Flags'
        value={canyonFlags.join(', ')}
        testId='stat-canyon-flags'
      />
    );
  }

  if (hasClimbingType) {
    technicalItems.push(
      <StatItem
        key='climbing-type'
        icon={<Activity className='h-4 w-4' />}
        label='Climbing Type'
        value={climbingType}
        testId='stat-climbing-type'
      />
    );
  }

  if (hasClimbingGrade) {
    technicalItems.push(
      <StatItem
        key='climbing-grade'
        icon={<Compass className='h-4 w-4' />}
        label='Climbing Grade'
        value={climbingGrade}
        testId='stat-climbing-grade'
      />
    );
  }

  if (hasClimbingLength) {
    technicalItems.push(
      <StatItem
        key='climbing-length'
        icon={<Ruler className='h-4 w-4' />}
        label='Climbing Length'
        value={`${climbingLength} m`}
        testId='stat-climbing-length'
      />
    );
  }

  const sections = [
    {
      key: 'performance',
      title: 'Performance',
      description: 'Distance, duration, pace, and effort metrics.',
      items: performanceItems,
    },
    {
      key: 'context',
      title: 'Route & Conditions',
      description: 'Route context, terrain, and current conditions.',
      items: contextItems,
    },
    {
      key: 'technical',
      title: 'Technical Details',
      description: 'Activity-specific grades, lengths, and specialist details.',
      items: technicalItems,
    },
  ].filter(section => section.items.length > 0);

  if (sections.length === 0) {
    return null; // Don't render empty card
  }

  return (
    <Card className={className} data-testid='activity-stats-grid'>
      <CardHeader className='pb-4'>
        <CardTitle className='text-base'>Activity highlights</CardTitle>
        <CardDescription>
          Performance, route context, and technical details for this activity.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        {sections.map((section, index) => (
          <div key={section.key} className='space-y-4'>
            <StatsSection
              title={section.title}
              description={section.description}
              items={section.items}
              testId={`activity-stats-section-${section.key}`}
            />
            {index < sections.length - 1 && <Separator />}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
