"""PDF renderer for the outdoor logbook export.

Takes the LogbookExportData contracts from the data service
and renders them into a downloadable PDF byte stream.
"""

import io
from datetime import UTC, datetime
from xml.sax.saxutils import escape as xml_escape

from core_shared.models.journals import (
    LogbookEntryData,
    LogbookExportData,
    LogbookYearlySummary,
    ParticipantIndexEntry,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _safe_str(text: object) -> str:
    """Escape XML special characters for ReportLab Paragraphs."""
    if text is None:
        return ""
    return xml_escape(str(text))


class LogbookPdfRenderer:
    """Renders LogbookExportData into a PDF byte stream."""

    # Layout constants
    _PAGE_WIDTH, _PAGE_HEIGHT = A4
    _MARGIN = 2.0 * cm

    # Colours
    _HEADER_BG = colors.HexColor("#1a365d")  # Dark navy
    _HEADER_TEXT = colors.white
    _SECTION_BG = colors.HexColor("#e2e8f0")  # Slate-200
    _ACCENT = colors.HexColor("#2b6cb0")  # Blue-600
    _LIGHT_ROW = colors.HexColor("#f7fafc")  # Gray-50
    _TABLE_BORDER = colors.HexColor("#cbd5e0")  # Gray-300

    def render(self, data: LogbookExportData) -> bytes:
        """Render the logbook data to PDF bytes."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=self._MARGIN,
            rightMargin=self._MARGIN,
            topMargin=self._MARGIN,
            bottomMargin=self._MARGIN,
        )

        styles = self._build_styles()
        story: list[object] = []

        # Cover page
        self._render_cover(story, data, styles)

        # Journal entries
        if data.entries:
            story.append(Spacer(1, 12 * mm))
            for entry in data.entries:
                self._render_entry(story, entry, styles, depth=0)

        # Yearly summaries
        if data.yearly_summaries:
            self._render_summaries(story, data.yearly_summaries, styles)

        # Participant index
        if data.participant_index:
            self._render_participant_index(story, data.participant_index, styles)

        doc.build(story)
        return buffer.getvalue()

    # ── Style definitions ─────────────────────────────────────

    def _build_styles(self) -> dict[str, ParagraphStyle]:
        """Build the stylesheet for the PDF."""
        base = getSampleStyleSheet()
        styles: dict[str, ParagraphStyle] = {}

        styles["title"] = ParagraphStyle(
            "LogbookTitle",
            parent=base["Title"],
            fontSize=28,
            leading=34,
            textColor=self._HEADER_BG,
            spaceAfter=6 * mm,
        )

        styles["subtitle"] = ParagraphStyle(
            "LogbookSubtitle",
            parent=base["Normal"],
            fontSize=14,
            leading=18,
            textColor=colors.gray,
            spaceAfter=4 * mm,
        )

        styles["heading1"] = ParagraphStyle(
            "LogbookH1",
            parent=base["Heading1"],
            fontSize=18,
            leading=22,
            textColor=self._HEADER_BG,
            spaceBefore=8 * mm,
            spaceAfter=4 * mm,
        )

        styles["heading2"] = ParagraphStyle(
            "LogbookH2",
            parent=base["Heading2"],
            fontSize=14,
            leading=18,
            textColor=self._ACCENT,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        )

        styles["entry_title"] = ParagraphStyle(
            "EntryTitle",
            parent=base["Heading3"],
            fontSize=12,
            leading=16,
            textColor=self._HEADER_BG,
            spaceBefore=4 * mm,
            spaceAfter=1 * mm,
        )

        styles["body"] = ParagraphStyle(
            "LogbookBody",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            spaceAfter=2 * mm,
        )

        styles["small"] = ParagraphStyle(
            "LogbookSmall",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.gray,
        )

        styles["label"] = ParagraphStyle(
            "LogbookLabel",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=self._ACCENT,
        )

        styles["section_heading"] = ParagraphStyle(
            "SectionHeading",
            parent=base["Heading2"],
            fontSize=16,
            leading=20,
            textColor=self._HEADER_BG,
            spaceBefore=10 * mm,
            spaceAfter=4 * mm,
        )

        return styles

    # ── Cover page ────────────────────────────────────────────

    def _get_all_dates(self, entries: list[LogbookEntryData]) -> list[datetime]:
        """Get all dates from a list of entries and their children."""
        dates = []
        for e in entries:
            dates.append(e.event_date_range.start)
            dates.append(e.event_date_range.end)
            if e.children:
                dates.extend(self._get_all_dates(e.children))
        return dates

    def _render_cover(
        self,
        story: list[object],
        data: LogbookExportData,
        styles: dict[str, ParagraphStyle],
    ) -> None:
        """Render the cover page."""
        story.append(Spacer(1, 40 * mm))
        story.append(Paragraph("Outdoor Logbook", styles["title"]))

        # Date range
        all_dates = self._get_all_dates(data.entries)
        if all_dates:
            first_date = min(all_dates)
            last_date = max(all_dates)
            date_str = (
                f"{first_date.strftime('%d/%m/%Y')} — {last_date.strftime('%d/%m/%Y')}"
            )
            story.append(Paragraph(date_str, styles["subtitle"]))

        story.append(
            Paragraph(
                f"Generated {datetime.now(tz=UTC).strftime('%d/%m/%Y')}",
                styles["small"],
            )
        )

        # Entry count summary
        entry_count = self._count_all_entries(data.entries)
        story.append(Spacer(1, 8 * mm))
        story.append(
            Paragraph(
                f"{entry_count} journal entries",
                styles["subtitle"],
            )
        )

    def _count_all_entries(self, entries: list[LogbookEntryData]) -> int:
        """Count total entries including children."""
        count = 0
        for entry in entries:
            count += 1
            count += self._count_all_entries(entry.children)
        return count

    # ── Journal entry rendering ───────────────────────────────

    def _render_entry(
        self,
        story: list[object],
        entry: LogbookEntryData,
        styles: dict[str, ParagraphStyle],
        depth: int = 0,
    ) -> None:
        """Render a single journal entry with indentation for hierarchy."""
        indent = depth * 10 * mm

        # Title with date and type labels
        date_str = entry.event_date_range.start.strftime("%d/%m/%Y")
        types_str = ", ".join(t.replace("_", " ").title() for t in entry.journal_types)
        types_label = f' <font color="gray" size="8">[{types_str}]</font>'

        title_style = ParagraphStyle(
            f"EntryTitle_d{depth}",
            parent=styles["entry_title"],
            leftIndent=indent,
        )
        story.append(
            Paragraph(
                f"{_safe_str(entry.title)} — {date_str}{types_label}",
                title_style,
            )
        )

        body_style = ParagraphStyle(
            f"Body_d{depth}",
            parent=styles["body"],
            leftIndent=indent + 4 * mm,
        )
        small_style = ParagraphStyle(
            f"Small_d{depth}",
            parent=styles["small"],
            leftIndent=indent + 4 * mm,
        )
        label_style = ParagraphStyle(
            f"Label_d{depth}",
            parent=styles["label"],
            leftIndent=indent + 4 * mm,
        )

        # Content
        if entry.content:
            story.append(Paragraph(_safe_str(entry.content), body_style))

        # Template / Gear item names
        if entry.template_name:
            story.append(
                Paragraph(f"Template: {_safe_str(entry.template_name)}", label_style)
            )
        if entry.gear_item_name:
            story.append(
                Paragraph(f"Gear Item: {_safe_str(entry.gear_item_name)}", label_style)
            )

        # Outdoor activity data
        if entry.outdoor_activity_data:
            oa = entry.outdoor_activity_data
            parts = []
            if oa.weather_conditions:
                parts.append(f"Weather: {_safe_str(oa.weather_conditions)}")
            if oa.role:
                parts.append(f"Role: {_safe_str(oa.role)}")
            if oa.in_leadership_role:
                parts.append("In leadership role")
            if oa.participant_notes:
                parts.append(f"Notes: {_safe_str(oa.participant_notes)}")
            if parts:
                story.append(Paragraph(" | ".join(parts), small_style))

        # Fitness data
        if entry.fitness_data:
            self._render_fitness_data(story, entry.fitness_data, small_style)

        # Abseil pitches
        if entry.abseil_pitches:
            self._render_pitch_table(story, entry, indent + 4 * mm, styles)

        # Abseiling summary (when no individual pitches)
        elif entry.abseiling_data:
            ab = entry.abseiling_data
            parts = []
            if ab.number_of_abseils is not None:
                parts.append(f"Abseils: {ab.number_of_abseils}")
            if ab.total_length is not None:
                parts.append(f"Total length: {ab.total_length}m")
            if ab.number_of_setups is not None:
                parts.append(f"Setups: {ab.number_of_setups}")
            if ab.number_of_rescues is not None:
                parts.append(f"Rescues: {ab.number_of_rescues}")
            if parts:
                story.append(Paragraph(" | ".join(parts), small_style))

        # Type-specific data sections
        self._render_type_specific_data(story, entry, small_style)

        # Contacts
        if entry.contacts:
            names = [
                f"{_safe_str(c.name)} ({_safe_str(c.role).lower()})"
                for c in entry.contacts
            ]
            story.append(Paragraph(f"Participants: {', '.join(names)}", small_style))

        # Immich photo album shared link (ITER11-005 Phase 2)
        if entry.album_shared_link:
            url = _safe_str(entry.album_shared_link)
            story.append(
                Paragraph(
                    f'\U0001f4f7 Photo Album: <a href="{url}">{url}</a>',
                    small_style,
                )
            )

        # Spacing between entries
        story.append(Spacer(1, 2 * mm))

        # Render children recursively
        for child in entry.children:
            self._render_entry(story, child, styles, depth + 1)

    def _render_fitness_data(
        self,
        story: list[object],
        fitness: object,
        style: ParagraphStyle,
    ) -> None:
        """Render fitness data metrics."""
        parts = []
        if hasattr(fitness, "distance") and fitness.distance is not None:
            parts.append(f"Distance: {fitness.distance}m")
        if hasattr(fitness, "elevation_gain") and fitness.elevation_gain is not None:
            parts.append(f"Elevation: {fitness.elevation_gain}m")
        if hasattr(fitness, "duration") and fitness.duration is not None:
            parts.append(f"Duration: {fitness.duration}s")
        if hasattr(fitness, "heart_rate_avg") and fitness.heart_rate_avg is not None:
            parts.append(f"Avg HR: {fitness.heart_rate_avg}bpm")
        if hasattr(fitness, "heart_rate_max") and fitness.heart_rate_max is not None:
            parts.append(f"Max HR: {fitness.heart_rate_max}bpm")
        if hasattr(fitness, "calories") and fitness.calories is not None:
            parts.append(f"Calories: {fitness.calories}")
        if parts:
            story.append(Paragraph(" | ".join(parts), style))

    def _render_pitch_table(
        self,
        story: list[object],
        entry: LogbookEntryData,
        left_indent: float,
        styles: dict[str, ParagraphStyle],
    ) -> None:
        """Render abseil pitches as a table."""
        label_style = ParagraphStyle(
            "PitchLabel",
            parent=styles["label"],
            leftIndent=left_indent,
        )
        story.append(Paragraph("Abseil Pitches:", label_style))

        # Determine which optional columns to include.
        # If ALL pitches have None for a field, omit that column entirely.
        # If only some are None, include the column but render empty for those.
        include_setup = any(
            pitch.did_setup is not None for pitch in entry.abseil_pitches
        )
        include_rescue = any(
            pitch.did_rescue is not None for pitch in entry.abseil_pitches
        )

        headers: list[str] = ["#", "Height (m)", "Anchor Location", "Anchor Type"]
        if include_setup:
            headers.append("Setup")
        if include_rescue:
            headers.append("Rescue")
        table_data: list[list[str]] = [headers]

        for pitch in entry.abseil_pitches:
            row: list[str] = [
                str(pitch.pitch_number),
                str(pitch.height) if pitch.height is not None else "\u2014",
                pitch.anchor_location or "\u2014",
                pitch.anchor_type or "\u2014",
            ]
            if include_setup:
                if pitch.did_setup is None:
                    row.append("")
                else:
                    row.append("Yes" if pitch.did_setup else "No")
            if include_rescue:
                if pitch.did_rescue is None:
                    row.append("")
                else:
                    row.append("Yes" if pitch.did_rescue else "No")
            table_data.append(row)

        # Abseiling summary row
        if entry.abseiling_data:
            ab = entry.abseiling_data
            summary_row: list[str] = [
                "Total",
                str(ab.total_length) if ab.total_length is not None else "\u2014",
                "",
                "",
            ]
            if include_setup:
                summary_row.append(
                    str(ab.number_of_setups)
                    if ab.number_of_setups is not None
                    else "\u2014"
                )
            if include_rescue:
                summary_row.append(
                    str(ab.number_of_rescues)
                    if ab.number_of_rescues is not None
                    else "\u2014"
                )
            table_data.append(summary_row)

        num_cols = len(headers)
        avail_width = max(
            self._PAGE_WIDTH - 2 * self._MARGIN - left_indent,
            50 * mm,  # clamp to a minimum width to prevent crash on deep nesting
        )

        # Distribute column widths based on included columns
        base_widths = [0.06, 0.14, 0.20, 0.30]
        optional_widths: list[float] = []
        if include_setup:
            optional_widths.append(0.15)
        if include_rescue:
            optional_widths.append(0.15)
        # Scale base widths to fill remaining space after optional columns
        optional_total = sum(optional_widths)
        base_total = sum(base_widths)
        base_scale = (1.0 - optional_total) / base_total
        col_widths = [avail_width * (w * base_scale) for w in base_widths]
        col_widths.extend(avail_width * w for w in optional_widths)
        assert len(col_widths) == num_cols

        table = Table(table_data, colWidths=col_widths)
        table_style = TableStyle(
            [
                # Header row
                ("BACKGROUND", (0, 0), (-1, 0), self._HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), self._HEADER_TEXT),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, self._TABLE_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )

        # Alternate row colours
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                table_style.add("BACKGROUND", (0, i), (-1, i), self._LIGHT_ROW)

        # Summary row styling
        if entry.abseiling_data:
            last_row = len(table_data) - 1
            table_style.add(
                "BACKGROUND", (0, last_row), (-1, last_row), self._SECTION_BG
            )
            table_style.add("FONTNAME", (0, last_row), (-1, last_row), "Helvetica-Bold")

        table.setStyle(table_style)
        story.append(table)
        story.append(Spacer(1, 2 * mm))

    def _render_type_specific_data(
        self,
        story: list[object],
        entry: LogbookEntryData,
        style: ParagraphStyle,
    ) -> None:
        """Render type-specific data fields."""
        parts: list[str] = []

        if entry.canyoning_data:
            cd = entry.canyoning_data
            if hasattr(cd, "french_grade") and cd.french_grade:
                parts.append(f"Grade: {_safe_str(cd.french_grade)}")
            if hasattr(cd, "canyon_type") and cd.canyon_type:
                parts.append(f"Type: {_safe_str(cd.canyon_type)}")

        if entry.caving_data:
            cv = entry.caving_data
            if cv.is_vertical:
                parts.append("Vertical cave")
            if cv.is_horizontal:
                parts.append("Horizontal cave")

        if entry.climbing_data:
            cl = entry.climbing_data
            if hasattr(cl, "climbing_type") and cl.climbing_type:
                parts.append(f"Climbing type: {_safe_str(cl.climbing_type)}")
            if hasattr(cl, "grade") and cl.grade:
                parts.append(f"Grade: {_safe_str(cl.grade)}")

        if entry.kayaking_data:
            kd = entry.kayaking_data
            if kd.is_white_water:
                parts.append("White water")
            if kd.rapids_grade:
                parts.append(f"Rapids grade: {_safe_str(kd.rapids_grade)}")

        if entry.bushwalking_data:
            bw = entry.bushwalking_data
            if hasattr(bw, "track_type") and bw.track_type:
                parts.append(f"Track: {_safe_str(bw.track_type)}")

        if entry.canoeing_data:
            cn = entry.canoeing_data
            if cn.water_type:
                parts.append(f"Water type: {_safe_str(cn.water_type)}")

        if entry.gear_maintenance_data:
            gm = entry.gear_maintenance_data
            if gm.maintenance_type:
                parts.append(f"Maintenance: {_safe_str(gm.maintenance_type)}")
            if hasattr(gm, "retirement_reason") and gm.retirement_reason:
                parts.append(f"Retirement reason: {_safe_str(gm.retirement_reason)}")

        if entry.outdoor_training_data:
            ot = entry.outdoor_training_data
            if hasattr(ot, "focus_areas") and ot.focus_areas:
                areas = (
                    ot.focus_areas
                    if isinstance(ot.focus_areas, list)
                    else [ot.focus_areas]
                )
                safe_areas = [_safe_str(str(a)) for a in areas]
                parts.append(f"Focus: {', '.join(safe_areas)}")

        if entry.outdoor_planning_data:
            op = entry.outdoor_planning_data
            if hasattr(op, "topics") and op.topics:
                parts.append(f"Topics: {_safe_str(op.topics)}")

        if parts:
            story.append(Paragraph(" | ".join(parts), style))

    # ── Yearly summary pages ──────────────────────────────────

    def _render_summaries(
        self,
        story: list[object],
        summaries: list[LogbookYearlySummary],
        styles: dict[str, ParagraphStyle],
    ) -> None:
        """Render yearly summary pages."""
        story.append(Paragraph("Yearly Summaries", styles["section_heading"]))

        for summary in summaries:
            story.append(Paragraph(f"Year {summary.year}", styles["heading2"]))

            # Activities by type table
            if summary.total_activities_by_type:
                headers = ["Activity Type", "Total", "Leadership"]
                table_data = [headers]
                for act_type, count in sorted(summary.total_activities_by_type.items()):
                    leadership_count = summary.leadership_activities_by_type.get(
                        act_type, 0
                    )
                    row = [
                        act_type.replace("_", " ").title(),
                        str(count),
                        str(leadership_count),
                    ]
                    table_data.append(row)

                avail_width = self._PAGE_WIDTH - 2 * self._MARGIN
                col_widths = [
                    avail_width * 0.50,
                    avail_width * 0.25,
                    avail_width * 0.25,
                ]
                table = Table(table_data, colWidths=col_widths)
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), self._HEADER_BG),
                            ("TEXTCOLOR", (0, 0), (-1, 0), self._HEADER_TEXT),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                            ("GRID", (0, 0), (-1, -1), 0.5, self._TABLE_BORDER),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]
                    )
                )
                story.append(table)
                story.append(Spacer(1, 4 * mm))

            # Abseiling statistics
            abseil_data = [
                ["Metric", "Value"],
                ["Total Abseiling Metres", str(summary.total_abseiling_metres)],
                ["Total Abseils", str(summary.total_abseils)],
                ["Total Setups", str(summary.total_setups)],
                ["Total Rescues", str(summary.total_rescues)],
            ]

            avail_width = self._PAGE_WIDTH - 2 * self._MARGIN
            col_widths = [avail_width * 0.60, avail_width * 0.40]
            abseil_table = Table(abseil_data, colWidths=col_widths)
            abseil_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), self._HEADER_BG),
                        ("TEXTCOLOR", (0, 0), (-1, 0), self._HEADER_TEXT),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("ALIGN", (1, 0), (1, -1), "CENTER"),
                        ("GRID", (0, 0), (-1, -1), 0.5, self._TABLE_BORDER),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(abseil_table)
            story.append(Spacer(1, 6 * mm))

    # ── Participant index ─────────────────────────────────────

    def _render_participant_index(
        self,
        story: list[object],
        participants: list[ParticipantIndexEntry],
        styles: dict[str, ParagraphStyle],
    ) -> None:
        """Render the participant index as a sorted table."""
        story.append(Paragraph("Participant Index", styles["section_heading"]))
        story.append(
            Paragraph(
                "Contacts appearing in 3 or more journal entries.",
                styles["small"],
            )
        )
        story.append(Spacer(1, 2 * mm))

        headers = ["Name", "Appearances"]
        table_data = [headers]
        for p in participants:
            table_data.append([p.name, str(p.appearances)])

        avail_width = self._PAGE_WIDTH - 2 * self._MARGIN
        col_widths = [avail_width * 0.70, avail_width * 0.30]
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), self._HEADER_BG),
                    ("TEXTCOLOR", (0, 0), (-1, 0), self._HEADER_TEXT),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 0), (1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.5, self._TABLE_BORDER),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )

        # Alternate row colours
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, i), (-1, i), self._LIGHT_ROW),
                        ]
                    )
                )

        story.append(table)
