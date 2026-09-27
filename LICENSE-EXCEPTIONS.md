# Licence Exceptions

This project is licensed under the GNU Affero General Public License, version 3 or (at your
option) any later version (see [LICENSE](LICENSE)). The copyright holders grant the following
additional permission under section 7 of that licence.

## react-leaflet

> **Additional permission under GNU AGPL version 3 section 7**
>
> If you modify this Program, or any covered work, by linking or combining it with
> react-leaflet or @react-leaflet/core (or a modified version of either library), containing
> parts covered by the terms of the Hippocratic License, version 2.1, the licensors of this
> Program grant you additional permission to convey the resulting work.

This permission applies under AGPL-3.0 and under any later version of the AGPL that you choose
to apply to the Program.

### What this means

- **Why it is needed.** The frontend's map component uses
  [react-leaflet](https://github.com/PaulLeCam/react-leaflet), which is licensed under the
  [Hippocratic License 2.1](https://firstdonoharm.dev/version/2/1/license/). That licence
  adds use conditions (compliance with human-rights principles) and an arbitration clause, which
  the AGPL would otherwise treat as "further restrictions" (section 10).
- **What it covers.** Only this project's own code: the permission lets this project's
  AGPL-licensed code be conveyed together with react-leaflet. It does not relicense
  react-leaflet.
- **react-leaflet keeps its own licence.** Anyone who conveys a copy of the frontend that
  includes react-leaflet must also meet the Hippocratic License's conditions for that part,
  including its notice requirement.
- **You may remove this permission.** Section 7 allows recipients to remove additional
  permissions from their copies and modified versions. If you do, you must also remove
  react-leaflet, for example by using [Leaflet](https://leafletjs.com/) (BSD-2-Clause) directly,
  before conveying the work.
- **Package metadata.** Package manifests keep the SPDX identifier `AGPL-3.0-or-later`. An
  additional permission only adds rights, so the AGPL remains the minimum every recipient gets.
  SPDX's `WITH` operator accepts only exceptions on the SPDX list, which rules out a
  project-specific one.
- **Contributions.** Contributions to this project are accepted under the AGPL together with the
  permissions in this file.

The [third-party licence audit](docs/licensing/third-party-licences.md) records every runtime
dependency's licence and why each one is compatible.
