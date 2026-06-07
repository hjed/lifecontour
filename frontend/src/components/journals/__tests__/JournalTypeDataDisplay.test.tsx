/**
 * Tests for JournalTypeDataDisplay component.
 *
 * Tests type-specific data display for different journal types.
 */

import { render, screen } from '@testing-library/react';
import { JournalTypeDataDisplay } from '../JournalTypeDataDisplay';
import {
  JournalType,
  type MoodData,
  type PlanData,
  type TravelData,
  type PhotoAlbumData,
} from '@/types/journals';

describe('JournalTypeDataDisplay', () => {
  describe('Rendering', () => {
    it('renders nothing when no type data', () => {
      const { container } = render(
        <JournalTypeDataDisplay types={[JournalType.NOTE]} />
      );

      expect(container.firstChild).toBeNull();
    });

    it('renders nothing when type data is empty', () => {
      const { container } = render(
        <JournalTypeDataDisplay types={[JournalType.NOTE]} typeData={{}} />
      );

      expect(container.firstChild).toBeNull();
    });

    it('applies custom className', () => {
      const moodData: MoodData = {
        mood_value: 8,
        mood_label: 'Happy',
        energy_level: 7,
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.MOOD_RATING]}
          typeData={{ MOOD: moodData }}
          className='custom-class'
        />
      );

      expect(screen.getByTestId('type-data-display')).toHaveClass(
        'custom-class'
      );
    });
  });

  describe('MOOD Data Display', () => {
    it('renders mood data when MOOD_RATING type is present', () => {
      const moodData: MoodData = {
        mood_value: 8,
        mood_label: 'Happy',
        energy_level: 7,
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.MOOD_RATING]}
          typeData={{ MOOD: moodData }}
        />
      );

      expect(screen.getByTestId('mood-data')).toBeInTheDocument();
      expect(screen.getByText('Mood & Energy')).toBeInTheDocument();
      expect(screen.getByText('Happy')).toBeInTheDocument();
      expect(screen.getByText('7/10')).toBeInTheDocument();
    });

    it('renders mood value without label', () => {
      const moodData: MoodData = {
        mood_value: 6,
        mood_label: null,
        energy_level: null,
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.MOOD_RATING]}
          typeData={{ MOOD: moodData }}
        />
      );

      expect(screen.getByText('6/10')).toBeInTheDocument();
    });
  });

  describe('PLAN Data Display', () => {
    it('renders plan data when PLAN type is present', () => {
      const planData: PlanData = {
        documents: [
          {
            id: 'doc1',
            title: 'Meeting Notes',
            url: 'https://example.com/doc1',
          },
          {
            id: 'doc2',
            title: 'Project Plan',
            url: 'https://example.com/doc2',
          },
        ],
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.PLAN]}
          typeData={{ PLAN: planData }}
        />
      );

      expect(screen.getByTestId('plan-data')).toBeInTheDocument();
      expect(screen.getByText('Plan Documents')).toBeInTheDocument();
      expect(screen.getByText('Meeting Notes')).toBeInTheDocument();
      expect(screen.getByText('Project Plan')).toBeInTheDocument();
    });

    it('renders nothing when no documents', () => {
      const planData: PlanData = {
        documents: [],
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.PLAN]}
          typeData={{ PLAN: planData }}
        />
      );

      expect(screen.queryByTestId('plan-data')).not.toBeInTheDocument();
    });
  });

  describe('TRAVEL Data Display', () => {
    it('renders travel data when TRAVEL type is present', () => {
      const travelData: TravelData = {
        flights: [
          {
            id: 'flight1',
            flight_number: 'QF123',
            departure_airport: 'SYD',
            arrival_airport: 'MEL',
            booking_reference: 'ABC123',
            order: 1,
          },
        ],
        accommodations: [],
        transportation: [],
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.TRAVEL]}
          typeData={{ TRAVEL: travelData }}
        />
      );

      expect(screen.getByTestId('travel-data')).toBeInTheDocument();
      expect(screen.getByText('Travel Details')).toBeInTheDocument();
      expect(screen.getByText('QF123')).toBeInTheDocument();
      expect(screen.getByText('SYD → MEL')).toBeInTheDocument();
    });

    it('renders accommodations', () => {
      const travelData: TravelData = {
        flights: [],
        accommodations: [
          {
            id: 'acc1',
            name: 'Hotel Example',
            location: 'Melbourne',
            booking_reference: 'HOTEL123',
            order: 1,
          },
        ],
        transportation: [],
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.TRAVEL]}
          typeData={{ TRAVEL: travelData }}
        />
      );

      expect(screen.getByText('Hotel Example')).toBeInTheDocument();
      expect(screen.getByText('Melbourne')).toBeInTheDocument();
    });

    it('renders nothing when no travel details', () => {
      const travelData: TravelData = {
        flights: [],
        accommodations: [],
        transportation: [],
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.TRAVEL]}
          typeData={{ TRAVEL: travelData }}
        />
      );

      expect(screen.queryByTestId('travel-data')).not.toBeInTheDocument();
    });
  });

  describe('PHOTO_ALBUM Data Display', () => {
    it('renders the album name and link when PHOTO_ALBUM type is present', () => {
      const photoData: PhotoAlbumData = {
        immich_album_id: 'album-123',
        album_name: 'Summer Trip',
        album_url: 'https://immich.example.com/albums/album-123',
        asset_count: 12,
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.PHOTO_ALBUM]}
          typeData={{ PHOTO_ALBUM: photoData }}
        />
      );

      expect(screen.getByTestId('photo-album-data')).toBeInTheDocument();
      expect(screen.getByText('Photo Album')).toBeInTheDocument();
      const link = screen.getByRole('link', { name: 'Summer Trip' });
      expect(link).toHaveAttribute(
        'href',
        'https://immich.example.com/albums/album-123'
      );
      expect(screen.getByText(/12 photos/)).toBeInTheDocument();
    });

    it('falls back to a default label when the album has no name', () => {
      const photoData: PhotoAlbumData = {
        immich_album_id: 'album-123',
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.PHOTO_ALBUM]}
          typeData={{ PHOTO_ALBUM: photoData }}
        />
      );

      expect(screen.getByTestId('photo-album-data')).toBeInTheDocument();
      expect(screen.getByText('Immich album')).toBeInTheDocument();
    });

    it('renders nothing when no album id', () => {
      const photoData: PhotoAlbumData = {
        immich_album_id: null,
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.PHOTO_ALBUM]}
          typeData={{ PHOTO_ALBUM: photoData }}
        />
      );

      expect(screen.queryByTestId('photo-album-data')).not.toBeInTheDocument();
    });
  });

  describe('Multiple Types', () => {
    it('renders multiple type data sections', () => {
      const moodData: MoodData = {
        mood_value: 8,
        mood_label: 'Happy',
        energy_level: 7,
      };

      const photoData: PhotoAlbumData = {
        immich_album_id: 'album-123',
      };

      render(
        <JournalTypeDataDisplay
          types={[JournalType.MOOD_RATING, JournalType.PHOTO_ALBUM]}
          typeData={{ MOOD: moodData, PHOTO_ALBUM: photoData }}
        />
      );

      expect(screen.getByTestId('mood-data')).toBeInTheDocument();
      expect(screen.getByTestId('photo-album-data')).toBeInTheDocument();
    });
  });
});
