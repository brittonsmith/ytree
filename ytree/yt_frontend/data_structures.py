"""
Data structures for ytree frontend.




"""

#-----------------------------------------------------------------------------
# Copyright (c) ytree Development Team. All rights reserved.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

from yt.utilities.on_demand_imports import _h5py as h5py
import numpy as np
import json
import os
import stat

from .fields import YTreeFieldInfo

from yt.data_objects.static_output import \
    ParticleFile, \
    validate_index_order
from yt.frontends.halo_catalog.data_structures import \
    HaloCatalogFile
from yt.frontends.ytdata.data_structures import \
    SavedDataset
from yt.geometry.particle_geometry_handler import \
    ParticleIndex

from ytree.utilities.io import parse_h5_attr

_ptype = "halos"

class YTreeHDF5File(ParticleFile):
    def __init__(self, ds, io, filename, file_id, frange):
        with h5py.File(filename, mode="r") as f:
            self.total_particles_file = \
              {_ptype: f['data'].attrs['num_elements']}
        super().__init__(ds, io, filename, file_id, frange)

    def _read_particle_positions(self, ptype, f=None):
        raise NotImplementedError

    def _read_field_data(self, field, mask, f=None):
        if f is None:
            close = True
            f = h5py.File(self.filename, mode="r")
        else:
            close = False

        si = self.start
        ei = self.end
        data = f["data"][field][si:ei][mask].astype("float64")

        if close:
            f.close()

        return data

    def _get_particle_positions(self, ptype, f=None, transpose=True):
        if f is None:
            close = True
            f = h5py.File(self.filename, mode="r")
        else:
            close = False

        si = self.start
        ei = self.end
        pn = "data/position_%s"
        with h5py.File(self.filename, mode="r") as f:
            units = parse_h5_attr(f[pn % "x"], "units")
            pos = np.vstack(
                [f[pn % ax][si:ei].astype("float64") for ax in "xyz"]).T

        if close:
            f.close()

        dle = self.ds.domain_left_edge.to(units).v
        dw = self.ds.domain_width.to(units).v

        np.subtract(pos, dle, out=pos)
        np.mod(pos, dw, out=pos)
        np.add(pos, dle, out=pos)
        if transpose:
            pos = pos.T
        pos = self.ds.arr(pos, units)

        return pos

class YTreeDataset(SavedDataset):
    _index_class = ParticleIndex
    _file_class = YTreeHDF5File
    _field_info_class = YTreeFieldInfo
    _suffix = ".h5"
    _con_attrs = ("hubble_constant", "omega_matter", "omega_lambda")
    _force_periodicity = True

    def __init__(self, filename, dataset_type="ytree_arbor",
                 index_order=None,
                 units_override=None, unit_system="cgs"):
        self.index_order = validate_index_order(index_order)
        super().__init__(filename, dataset_type,
                         units_override=units_override,
                         unit_system=unit_system)

    def _set_derived_attrs(self):
        self.domain_center = 0.5 * (self.domain_right_edge +
                                    self.domain_left_edge)
        self.domain_width = self.domain_right_edge - self.domain_left_edge

    def _with_parameter_file_open(self, f):
        self.file_count = f.attrs['total_files']
        self.particle_count = f.attrs['total_nodes']
        self.box_size = self.quan(
            f.attrs['box_size'], f.attrs['box_size_units'])
        self._field_dict = json.loads(f.attrs['field_info'])

    def _parse_parameter_file(self):
        self.current_redshift = None
        self.current_time = None
        self.cosmological_simulation = 1
        self.dimensionality = 3
        prefix = self.parameter_filename[:-len(self._suffix)]
        self.filename_template = f"{prefix}_%(num)04d{self._suffix}"
        self.particle_types = (_ptype)
        self.particle_types_raw = (_ptype)
        super()._parse_parameter_file()
        # Set this again because unit registry has been updated.
        self.box_size = self.quan(self.box_size)
        self.domain_left_edge = self.box_size * \
          np.zeros(self.dimensionality)
        self.domain_right_edge = self.box_size * \
          np.ones(self.dimensionality)

    @classmethod
    def _is_valid(self, *args, **kwargs):
        if not args[0].endswith(".h5"): return False
        with h5py.File(args[0], "r") as f:
            if "data_type" in f.attrs and "arbor_type" in f.attrs:
                return True
        return False
