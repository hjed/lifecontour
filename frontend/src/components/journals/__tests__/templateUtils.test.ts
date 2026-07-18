import {
  templateTypeFieldUpdates,
  templateTypesForJournalTypes,
} from '../templateUtils';
import {
  ActivityTemplateType,
  JournalType,
  type ActivityTemplateResource,
} from '@/types/journals';

function makeTemplate(
  attributes: Partial<ActivityTemplateResource['attributes']> & {
    template_type: ActivityTemplateType;
  }
): ActivityTemplateResource {
  return {
    type: 'activity-templates',
    id: 'tpl-1',
    attributes: { name: 'Test', ...attributes },
  };
}

describe('templateTypesForJournalTypes', () => {
  it('always includes abseiling', () => {
    expect(templateTypesForJournalTypes([])).toEqual([
      ActivityTemplateType.ABSEILING,
    ]);
  });

  it('adds the derived type for canyoning/caving/climbing journals', () => {
    expect(
      templateTypesForJournalTypes([
        JournalType.CANYONING,
        JournalType.ABSEILING_TRIP,
        JournalType.FITNESS,
      ])
    ).toEqual([ActivityTemplateType.CANYONING, ActivityTemplateType.ABSEILING]);
    expect(templateTypesForJournalTypes([JournalType.CAVING])).toEqual([
      ActivityTemplateType.CAVING,
      ActivityTemplateType.ABSEILING,
    ]);
    expect(templateTypesForJournalTypes([JournalType.CLIMBING])).toEqual([
      ActivityTemplateType.CLIMBING,
      ActivityTemplateType.ABSEILING,
    ]);
  });
});

describe('templateTypeFieldUpdates', () => {
  it('maps canyoning template fields onto the canyoning block', () => {
    const updates = templateTypeFieldUpdates(
      makeTemplate({
        template_type: ActivityTemplateType.CANYONING,
        french_grade: 'v4a3IV',
        water_gauge_name: 'Kowmung',
        is_vertical: true,
      })
    );

    expect(updates).toEqual({
      journalType: JournalType.CANYONING,
      fields: {
        french_grade: 'v4a3IV',
        water_guage_name: 'Kowmung',
        is_vertical: true,
      },
    });
  });

  it('maps caving template fields onto the caving block', () => {
    const updates = templateTypeFieldUpdates(
      makeTemplate({
        template_type: ActivityTemplateType.CAVING,
        is_vertical: true,
        is_horizontal: false,
      })
    );

    expect(updates).toEqual({
      journalType: JournalType.CAVING,
      fields: { is_vertical: true, is_horizontal: false },
    });
  });

  it('maps climbing template fields onto the climbing block', () => {
    const updates = templateTypeFieldUpdates(
      makeTemplate({
        template_type: ActivityTemplateType.CLIMBING,
        climbing_type: 'sport',
        grade: 21,
        length: 30,
      })
    );

    expect(updates).toEqual({
      journalType: JournalType.CLIMBING,
      fields: { climbing_type: 'sport', grade: 21, length: 30 },
    });
  });

  it('returns null for abseiling templates and templates without fields', () => {
    expect(
      templateTypeFieldUpdates(
        makeTemplate({ template_type: ActivityTemplateType.ABSEILING })
      )
    ).toBeNull();
    expect(
      templateTypeFieldUpdates(
        makeTemplate({ template_type: ActivityTemplateType.CANYONING })
      )
    ).toBeNull();
  });
});
