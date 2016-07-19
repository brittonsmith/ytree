import functools
import h5py
import glob
import numpy as np
import os
import yt

from yt.frontends.ytdata.utilities import \
    _hdf5_yt_array, \
    _yt_array_hdf5_attr
from yt.units.unit_registry import \
    UnitRegistry
from yt.utilities.cosmology import \
    Cosmology

from .tree_node import \
    TreeNode
from .tree_node_selector import \
    tree_node_selector_registry
from .utilities import \
    _hdf5_yt_array_lite, \
    _hdf5_yt_attr

class Arbor(object):
    def __init__(self, filename):
        self.filename = filename
        self.unit_registry = UnitRegistry()
        self._load_trees()
        self._set_default_selector()
        self.cosmology = Cosmology(
            hubble_constant=self.hubble_constant,
            omega_matter=self.omega_matter,
            omega_lambda=self.omega_lambda,
            unit_registry=self.unit_registry)

    def set_selector(self, selector, *args, **kwargs):
        self.selector = tree_node_selector_registry.find(
            selector, *args, **kwargs)

    _arr = None
    @property
    def arr(self):
        if self._arr is not None:
            return self._arr
        self._arr = functools.partial(yt.YTArray, registry=self.unit_registry)
        return self._arr

    _quan = None
    @property
    def quan(self):
        if self._quan is not None:
            return self._quan
        self._quan = functools.partial(yt.YTQuantity, registry=self.unit_registry)
        return self._quan

    def _set_default_selector(self):
        for field in ["mass", "mvir"]:
            if field in self._field_data:
                self.set_selector("max_field_value", field)

    def _load_field_data(self):
        fh = h5py.File(self.filename, "r")
        for attr in ["hubble_constant",
                     "omega_matter",
                     "omega_lambda"]:
            setattr(self, attr, fh.attrs[attr])
        self.unit_registry.modify("h", self.hubble_constant)
        self.box_size = _hdf5_yt_attr(fh, "box_size",
                                      unit_registry=self.unit_registry)
        self._field_data = dict([(f, _hdf5_yt_array(fh["data"], f, self))
                                 for f in fh["data"]])
        fh.close()

    def _set_halo_id_field(self):
        _hfields = ["halo_id", "particle_identifier"]
        hfields = [f for f in _hfields
                   if f in self._field_data]
        if len(hfields) == 0:
            raise RuntimeError("No halo id field found.")
        self._hid_field = hfields[0]

    def _load_trees(self):
        self._load_field_data()
        self._set_halo_id_field()

        self.trees = []
        all_uid = self._field_data["tree_id"]
        if hasattr(all_uid, "units"):
            all_uid = all_uid.d
        all_uid = all_uid.astype(np.int64)
        root_ids = np.unique(all_uid)
        pbar = yt.get_pbar("Loading trees", root_ids.size)
        for my_i, root_id in enumerate(root_ids):
            tree_halos = (root_id == self._field_data["tree_id"])
            my_tree = {}
            for i in np.where(tree_halos)[0]:
                desc_id = np.int64(self._field_data["desc_id"][i])
                halo_id = np.int64(self._field_data[self._hid_field][i])
                uid = np.int64(self._field_data["uid"][i])
                if desc_id == -1:
                    level = 0
                else:
                    level = my_tree[desc_id].level_id + 1
                my_node = TreeNode(halo_id, level, i, arbor=self)
                my_tree[uid] = my_node
                if desc_id >= 0:
                    my_tree[desc_id].add_ancestor(my_node)
            self.trees.append(my_tree[root_id])
            pbar.update(my_i)
        pbar.finish()
        yt.mylog.info("Arbor contains %d trees with %d total nodes." %
                      (len(self.trees), self._field_data["uid"].size))

_ct_columns = (("a",        (0,)),
               ("uid",      (1,)),
               ("desc_id",  (3,)),
               ("mvir",     (10,)),
               ("rvir",     (11,)),
               ("position", (17, 18, 19)),
               ("velocity", (20, 21, 21)),
               ("tree_id",  (29,)),
               ("halo_id",  (30,)), # from halo finder
               ("snapshot", (31,)))
_ct_units = {"mvir": "Msun/h",
             "rvir": "kpc/h",
             "position": "Mpc/h",
             "velocity": "km/s"}
_ct_usecol = []
_ct_fields = {}
for field, col in _ct_columns:
    _ct_usecol.extend(col)
    _ct_fields[field] = np.arange(len(_ct_usecol)-len(col),
                                  len(_ct_usecol))

class ArborCT(Arbor):
    def _set_default_selector(self):
        self.set_selector("max_field_value", "mvir")

    def _read_cosmological_parameters(self):
        f = file(self.filename, "r")
        i = 0
        while True:
            i += 1
            line = f.readline()
            if line is None or not line.startswith("#"):
                break
            if "Omega_M" in line:
                pars = line[1:].split(";")
                for j, par in enumerate(["omega_matter",
                                         "omega_lambda",
                                         "hubble_constant"]):
                    v = float(pars[j].split(" = ")[1])
                    setattr(self, par, v)
            elif "Full box size" in line:
                pars = line.split("=")[1].strip().split()
                box = pars
        f.close()
        self._iheader = i
        self.unit_registry.modify("h", self.hubble_constant)
        self.box_size = self.quan(float(box[0]), box[1])

    def _load_field_data(self):
        yt.mylog.info("Loading tree data from %s." % self.filename)
        self._read_cosmological_parameters()
        data = np.loadtxt(self.filename, skiprows=self._iheader,
                          unpack=True, usecols=_ct_usecol)
        self._field_data = {}
        for field, cols in _ct_fields.items():
            if cols.size == 1:
                self._field_data[field] = data[cols][0]
            else:
                self._field_data[field] = np.rollaxis(data[cols], 1)
            if field in _ct_units:
                self._field_data[field] = \
                  yt.YTArray(self._field_data[field], _ct_units[field],
                             registry=self.unit_registry)
        self._field_data["redshift"] = 1. / self._field_data["a"] - 1.
        del self._field_data["a"]

class ArborTF(Arbor):
    def _set_default_selector(self):
        self.set_selector("max_field_value", "mass")

    def _load_trees(self):
        my_files = glob.glob(os.path.join(self.filename, "tree_segment_*.h5"))
        my_files.sort()

        fields = None
        self._field_data = \
          dict([(f, []) for f in ["uid", "desc_id",
                                  "tree_id", "redshift"]])

        offset = 0
        my_trees = None
        pbar = yt.get_pbar("Load segment files", len(my_files))
        for i, fn in enumerate(my_files):
            fh = h5py.File(fn, "r")
            if fields is None:
                for attr in ["omega_matter",
                             "omega_lambda",
                             "hubble_constant"]:
                    setattr(self, attr, fh.attrs[attr])
                self.unit_registry.modify("h", self.hubble_constant)
                self.domain_left_edge = \
                  _hdf5_yt_attr(fh, "domain_left_edge",
                                unit_registry=self.unit_registry)
                self.domain_right_edge = \
                  _hdf5_yt_attr(fh, "domain_right_edge",
                                unit_registry=self.unit_registry)
                self.box_size = (self.domain_right_edge -
                                 self.domain_left_edge)[0]

                fields = []
                for field in fh["data"]:
                    if field.startswith("descendent_"):
                        fields.append(field[len("descendent_"):])
                self._field_data.update(dict([(f, []) for f in fields]))

            if my_trees is None:
                des_ids = fh["data/descendent_particle_identifier"].value
                self._field_data["redshift"].append(
                    fh.attrs["descendent_current_redshift"] *
                    np.ones(des_ids.size))
                for field in fields:
                    self._field_data[field].append(
                        _hdf5_yt_array_lite(fh, "data/descendent_%s" % field))
            else:
                des_ids = anc_ids

            anc_ids = fh["data/ancestor_particle_identifier"].value
            self._field_data["redshift"].append(
                fh.attrs["ancestor_current_redshift"] *
                np.ones(anc_ids.size))
            for field in fields:
                self._field_data[field].append(
                    _hdf5_yt_array_lite(fh, "data/ancestor_%s" % field))
            links = fh["data/links"].value
            fh.close()

            if my_trees is None:
                fsize = des_ids.size
                self._field_data["uid"].append(
                    np.arange(offset, offset + fsize, dtype=np.int64))
                self._field_data["desc_id"].append(
                    -np.ones(fsize, dtype=np.int64))
                self._field_data["tree_id"].append(
                    self._field_data["uid"][0])
                des_nodes = [TreeNode(my_id, i, gid+offset, arbor=self)
                             for gid, my_id in enumerate(des_ids)]
                my_trees = des_nodes
                offset += fsize
            else:
                des_nodes = anc_nodes

            fsize = anc_ids.size
            self._field_data["uid"].append(
                np.arange(offset, offset + fsize, dtype=np.int64))
            self._field_data["desc_id"].append(
                -np.ones(fsize, dtype=np.int64))
            self._field_data["tree_id"].append(
                -np.ones(fsize, dtype=np.int64))
            anc_nodes = [TreeNode(my_id, i+1, gid+offset, arbor=self)
                         for gid, my_id in enumerate(anc_ids)]
            offset += fsize

            for link in links:
                i_des = np.where(link[0] == des_ids)[0][0]
                i_anc = np.where(link[1] == anc_ids)[0][0]
                des_nodes[i_des].add_ancestor(anc_nodes[i_anc])
                self._field_data["desc_id"][-1][i_anc] = \
                  self._field_data["uid"][-2][i_des]
                self._field_data["tree_id"][-1][i_anc] = \
                  self._field_data["tree_id"][-2][i_des]
            pbar.update(i)
        pbar.finish()

        self.trees = my_trees

        for field in self._field_data:
            pbar = yt.get_pbar("Preparing %s data" % field,
                               len(self._field_data[field]))
            my_data = []
            units = ""
            if isinstance(self._field_data[field][0], tuple):
                units = self._field_data[field][0][1]
            if units == "dimensionless": units = ""
            for i, level in enumerate(self._field_data[field]):
                if isinstance(level, tuple):
                    my_data.extend(level[0])
                else:
                    my_data.extend(level)
                pbar.update(i)
            if units != "":
                my_data = self.arr(my_data, units)
            else:
                my_data = np.array(my_data)
            self._field_data[field] = my_data
            pbar.finish()

        yt.mylog.info("Arbor contains %d trees with %d total nodes." %
                      (len(self.trees), offset))