import { render, screen } from '@testing-library/react';
import { ActivityStats } from '../ActivityStats';
import type { FitnessData } from '@/types/journals';
import type { Route } from '@/types/routes';

describe('ActivityStats', () => {
  const completeData: FitnessData = {
    distance: 5000,
    duration: 1800, // 30 mins
    elevation_gain: 150,
    calories: 450,
    heart_rate_avg: 145,
    heart_rate_max: 180,
  };

  it('renders all complete stats formats correctly', () => {
    render(<ActivityStats data={completeData} />);

    // Distance
    expect(screen.getByTestId('stat-distance')).toHaveTextContent('5.00 km');

    // Duration is '30:00' because the h formatting only triggers on > 0 hours
    expect(screen.getByTestId('stat-duration')).toHaveTextContent('30:00');

    // Pace
    // Pace = 30 mins (1800s) / 5 km = 360s/km = 6:00 /km
    expect(screen.getByTestId('stat-pace')).toHaveTextContent('6:00 /km');

    // Elevation Gain
    expect(screen.getByTestId('stat-elevation')).toHaveTextContent('150 m');

    // Calories
    expect(screen.getByTestId('stat-calories')).toHaveTextContent('450 kcal');

    // Heart Rate
    expect(screen.getByTestId('stat-hr')).toHaveTextContent('145 bpm');
  });

  it('handles minimum data gracefully', () => {
    render(<ActivityStats data={{}} />);

    // It should render exactly 0 stats (returns early)
    expect(screen.queryByTestId('activity-stats-grid')).not.toBeInTheDocument();
  });

  it('handles partial data gracefully', () => {
    render(<ActivityStats data={{ distance: 1000 }} />);

    // Will show distance, but Pace won't be shown since duration is missing
    expect(screen.getByTestId('stat-distance')).toHaveTextContent('1.00 km');
    expect(screen.queryByTestId('stat-pace')).not.toBeInTheDocument();
    expect(screen.queryByTestId('stat-duration')).not.toBeInTheDocument();
  });

  it('formats hours properly', () => {
    // 1 hr, 5 mins, 30s
    render(
      <ActivityStats data={{ duration: 3600 + 300 + 30, distance: 1000 }} />
    );

    expect(screen.getByTestId('stat-duration')).toHaveTextContent('1:05:30');
  });

  it('renders outdoor, jogging, and bushwalking data correctly', () => {
    const outdoorData = { weather_conditions: 'Sunny, 22°C' };
    const joggingData = { pace: 330 }; // 5:30 /km
    // track_grading uses the same "Grade X" format as BushwalkingTypeEditor stores
    const bushwalkingData = { track_grading: 'Grade 4' };

    render(
      <ActivityStats
        outdoorData={outdoorData}
        joggingData={joggingData}
        bushwalkingData={bushwalkingData}
      />
    );

    expect(screen.getByTestId('stat-weather')).toHaveTextContent('Sunny, 22°C');
    expect(screen.getByTestId('stat-pace-jogging')).toHaveTextContent(
      '5:30 /km'
    );
    // The track_grading value is stored and displayed as-is (already "Grade X")
    expect(screen.getByTestId('stat-grading')).toHaveTextContent('Grade 4');
  });

  it('renders route display when provided', () => {
    const routeDisplay: Route = {
      id: 'route-123',
      name: 'Blue Mountains Trail',
      description: 'A scenic bushwalk',
    };

    render(<ActivityStats routeDisplay={routeDisplay} data={{}} />);

    expect(screen.getByTestId('stat-route')).toHaveTextContent(
      'Blue Mountains Trail'
    );
  });

  it('renders complex activity type stats for multiple activity editors', () => {
    render(
      <ActivityStats
        data={{ distance: 12000 }}
        abseilingData={{ number_of_abseils: 6, total_length: 180 }}
        canyoningData={{
          french_grade: 'v3a2IV**',
          water_guage_name: 'Kowmung Gauge',
          water_guage_level: 8,
          is_vertical: true,
          is_night_canyon: true,
        }}
        climbingData={{ climbing_type: 'sport', grade: 18, length: 30 }}
        kayakingData={{ water_type: 'river' }}
        crossCountrySkiingData={{ snow_conditions: 'Fresh powder' }}
      />
    );

    expect(
      screen.getByTestId('activity-stats-section-performance')
    ).toHaveTextContent('Performance');
    expect(
      screen.getByTestId('activity-stats-section-context')
    ).toHaveTextContent('Route & Conditions');
    expect(
      screen.getByTestId('activity-stats-section-technical')
    ).toHaveTextContent('Technical Details');

    expect(screen.getByTestId('stat-abseils')).toHaveTextContent('6');
    expect(screen.getByTestId('stat-total-length')).toHaveTextContent('180 m');
    expect(screen.getByTestId('stat-french-grade')).toHaveTextContent(
      'v3a2IV**'
    );
    expect(screen.getByTestId('stat-water-gauge')).toHaveTextContent(
      'Kowmung Gauge (8)'
    );
    expect(screen.getByTestId('stat-canyon-flags')).toHaveTextContent(
      'Vertical, Night Canyon'
    );
    expect(screen.getByTestId('stat-climbing-type')).toHaveTextContent('sport');
    expect(screen.getByTestId('stat-climbing-grade')).toHaveTextContent('18');
    expect(screen.getByTestId('stat-climbing-length')).toHaveTextContent(
      '30 m'
    );
    expect(screen.getByTestId('stat-water-type')).toHaveTextContent('river');
    expect(screen.getByTestId('stat-snow-conditions')).toHaveTextContent(
      'Fresh powder'
    );
  });

  it('falls back to a default water gauge label when canyoning only provides a level', () => {
    render(
      <ActivityStats
        canyoningData={{
          water_guage_name: '',
          water_guage_level: 8,
        }}
      />
    );

    expect(screen.getByTestId('stat-water-gauge')).toHaveTextContent(
      'Gauge (8)'
    );
  });
});
