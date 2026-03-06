import { render, screen } from '@testing-library/react';
import { ActivityStats } from '../ActivityStats';
import type { FitnessData } from '@/types/journals';

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
    const bushwalkingData = { track_grading: '4' };

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
    expect(screen.getByTestId('stat-grading')).toHaveTextContent('Grade 4');
  });
});
